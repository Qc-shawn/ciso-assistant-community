import structlog
from django.contrib.auth import authenticate, password_validation
from core.serializer_fields import FieldsRelatedField

from .models import (
    PersonalAccessToken,
    User,
    Role, 
    Permission,
    )

from rest_framework import serializers
from .models import Team
from django.contrib.auth import get_user_model

logger = structlog.get_logger(__name__)

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(write_only=True)
    password = serializers.CharField(
        # This will be used when the DRF browsable API is enabled
        style={"input_type": "password"},
        trim_whitespace=False,
        write_only=True,
    )

    def validate(self, attrs):
        username = attrs.get("username")
        password = attrs.get("password")

        if username and password:
            user = authenticate(
                request=self.context.get("request"),
                username=username,
                password=password,
            )
            if not user:
                msg = "Unable to log in with provided credentials."
                raise serializers.ValidationError(msg, code="authorization")
        else:
            msg = 'Must include "username" and "password".'
            raise serializers.ValidationError(msg, code="authorization")

        attrs["user"] = user
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    """
    Serializer for password change endpoint.
    """

    old_password = serializers.CharField(
        max_length=128, write_only=True, required=True, style={"input_type": "password"}
    )
    new_password = serializers.CharField(
        max_length=128, write_only=True, required=True, style={"input_type": "password"}
    )
    confirm_new_password = serializers.CharField(
        max_length=128, write_only=True, required=True, style={"input_type": "password"}
    )

    def validate_new_password(self, data):
        password_validation.validate_password(data)
        return data

    def validate(self, data):
        if data["new_password"] != data["confirm_new_password"]:
            raise serializers.ValidationError(
                {"confirm_new_password": "The two password fields didn't match."}
            )
        return data


class SetPasswordSerializer(serializers.Serializer):
    """
    Serializer for password set endpoint as an administrator.
    """

    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    new_password = serializers.CharField(
        max_length=128, write_only=True, required=True, style={"input_type": "password"}
    )
    confirm_new_password = serializers.CharField(
        max_length=128, write_only=True, required=True, style={"input_type": "password"}
    )

    def validate_new_password(self, data):
        password_validation.validate_password(data)
        return data

    def validate(self, data):
        if data["new_password"] != data["confirm_new_password"]:
            raise serializers.ValidationError(
                {"confirm_new_password": "The two password fields didn't match."}
            )
        return data


class ResetPasswordConfirmSerializer(serializers.Serializer):
    """
    Serializer for password reset endpoint.
    """

    uidb64 = serializers.CharField(write_only=True)
    token = serializers.CharField(write_only=True)
    new_password = serializers.CharField(
        max_length=128, write_only=True, required=True, style={"input_type": "password"}
    )
    confirm_new_password = serializers.CharField(
        max_length=128, write_only=True, required=True, style={"input_type": "password"}
    )

    def validate_new_password(self, data):
        password_validation.validate_password(data)
        return data

    def validate(self, data):
        if data["new_password"] != data["confirm_new_password"]:
            raise serializers.ValidationError(
                {"confirm_new_password": "The two password fields didn't match."}
            )
        return data


class PersonalAccessTokenReadSerializer(serializers.ModelSerializer):
    """
    Serializer for PersonalAccessToken model.
    """

    user = FieldsRelatedField(["email", "id"])

    class Meta:
        model = PersonalAccessToken
        fields = ["name", "user", "created", "expiry", "digest"]

# ----------------------------------- CUSTOM ROLES SERIALIZER -----------------------------------
class RoleCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    permissions = serializers.ListField(
        child=serializers.CharField(), required=True
    )
    def validate_name(self, value):
        from iam.models import Role
        if Role.objects.filter(name=value).exists():
            raise serializers.ValidationError("A role with this name already exists.")
        return value

    def validate_permissions(self, value):
        from django.contrib.auth.models import Permission
        if not value or len(value) == 0:
            raise serializers.ValidationError("A role must have at least one permission.")
        perms = Permission.objects.filter(codename__in=value)
        if perms.count() != len(value):
            raise serializers.ValidationError("Some permissions are invalid.")
        return perms
# ----------------------------- CUSTOM ROLE GET SERIALIZER    -----------------------------

class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ['codename'] 

class RoleListSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = ['id', 'name', 'permissions']

    def get_permissions(self, obj):
        return list(obj.permissions.values_list('codename', flat=True))
        
# ----------------------------- CUSTOM ROLE UPDATE SERIALIZER -----------------------------

from iam.models import UserGroup, RoleAssignment
from django.contrib.auth.models import Permission
from django.db import transaction

class RoleUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(required=True)
    permissions = serializers.ListField(
        child=serializers.CharField(), required=True, write_only=True
    )

    def validate_permissions(self, value):
        if value == []:
            raise serializers.ValidationError("A role must have at least one permission.")
        invalid = [p for p in value if not Permission.objects.filter(codename=p).exists()]
        if invalid:
            raise serializers.ValidationError(f"Invalid permissions: {invalid}")
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        old_name = instance.name
        new_name = validated_data["name"].strip().lower()

        # 1. Update the role name and permissions
        instance.name = new_name
        instance.save()
        perms = Permission.objects.filter(codename__in=validated_data["permissions"])
        instance.permissions.set(perms)

        user_groups = UserGroup.objects.filter(name=old_name)
        processed_folders = set()
        for old_group in user_groups:
            processed_folders.add(old_group.folder_id)
            try:
                new_group = UserGroup.objects.get(name=new_name, folder=old_group.folder)
                if new_group.id != old_group.id:
                    for ra in RoleAssignment.objects.filter(user_group=old_group):
                        exists = RoleAssignment.objects.filter(
                            user_group=new_group,
                            role=ra.role,
                            folder=ra.folder,
                            user=ra.user,
                        ).exists()
                        if not exists:
                            ra.user_group = new_group
                            ra.save()
                        else:
                            ra.delete()
                    for user in old_group.user_set.all():
                        new_group.user_set.add(user)
                    old_group.delete()
                else:
                    old_group.name = new_name
                    old_group.save()
            except UserGroup.DoesNotExist:
                old_group.name = new_name
                old_group.save()
        
        for folder_id in processed_folders:
            dups = UserGroup.objects.filter(name=new_name, folder_id=folder_id)
            if dups.count() > 1:
                keep = dups.first()
                for extra in dups[1:]:
                    for ra in RoleAssignment.objects.filter(user_group=extra):
                        ra.user_group = keep
                        ra.save()
                    extra.delete()


        return instance

    def to_representation(self, instance):
        return {
            "id": str(instance.id),
            "name": instance.name,
            "permissions": list(instance.permissions.values_list("codename", flat=True)),
        }

# ========================= TEAM SERIALIZER =========================

User = get_user_model()

class TeamCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    user_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1
    )

    def validate_user_ids(self, value):
        users = User.objects.filter(id__in=value)
        if users.count() != len(value):
            raise serializers.ValidationError("One or more user IDs are invalid.")
        return value

    def create(self, validated_data):
        team = Team.objects.create(name=validated_data['name'])
        team.users.set(User.objects.filter(id__in=validated_data['user_ids']))
        return team
    
# ========================== TEAM UPDATE SERIALIZER =========================

class TeamUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    user_ids = serializers.ListField(child=serializers.UUIDField(), required=False)

    def validate_user_ids(self, value):
        if len(value) < 2:
            raise serializers.ValidationError("A team must have at least two users.")
        users = User.objects.filter(id__in=value)
        if users.count() != len(value):
            raise serializers.ValidationError("One or more user IDs are invalid.")
        return value

    def update(self, instance, validated_data):
        if 'name' in validated_data:
            instance.name = validated_data['name']
        if 'user_ids' in validated_data:
            users = User.objects.filter(id__in=validated_data['user_ids'])
            instance.users.set(users)
        instance.save()
        return instance
# ========================== TEAM LIST SERIALIZER =========================

class TeamListSerializer(serializers.ModelSerializer):
    users = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = ('id', 'name', 'users')

    def get_users(self, obj):
        return [
            {"id": str(user.id), "user email": user.username}
            for user in obj.users.all()
        ]
