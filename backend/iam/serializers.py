import structlog
from django.contrib.auth import authenticate, password_validation
from core.serializer_fields import FieldsRelatedField

from .models import (
    PersonalAccessToken,
    User,
    Role, 
    Permission,
    Team,
    UserGroup,
    RoleAssignment
    )

from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import transaction

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
    name = serializers.CharField(max_length=255, required=True)
    permissions = serializers.ListField(child=serializers.CharField(), required=True)

    # NEW scope controls
    apply_to_all_companies = serializers.BooleanField(required=False, default=False)
    select_specific_companies = serializers.BooleanField(required=False, default=False)
    company_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=False
    )

    def validate_name(self, value):
        from iam.models import Role
        if Role.objects.filter(name=value).exists():
            raise serializers.ValidationError("A role with this name already exists.")
        return value

    def validate_permissions(self, value):
        if not value:
            raise serializers.ValidationError("A role must have at least one permission.")
        perms = Permission.objects.filter(codename__in=value)
        if perms.count() != len(value):
            raise serializers.ValidationError("Some permissions are invalid.")
        return perms

    def validate(self, attrs):
        a_all = attrs.get("apply_to_all_companies", False)
        a_some = attrs.get("select_specific_companies", False)
        if a_all and a_some:
            raise serializers.ValidationError("Choose only one of the two radios.")
        if a_some and not attrs.get("company_ids"):
            raise serializers.ValidationError("company_ids is required when selecting specific companies.")
        return attrs

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

User = get_user_model()
class TeamUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False, allow_blank=False)
    add_user_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False
    )

    from uuid import UUID

    @transaction.atomic
    def update(self, instance, validated_data):
        errors = {}

        # 1. Update team name if provided
        if "name" in validated_data:
            name = validated_data["name"].strip()
            if not name:
                errors["name"] = "Team name cannot be blank."
            else:
                instance.name = name

        # 2. Add new members
        if "add_user_ids" in validated_data:
            raw_ids = validated_data["add_user_ids"]

            # Deduplicate input (ensure UUID objects)
            try:
                unique_ids = {self.UUID(str(uid)) for uid in raw_ids}
            except ValueError as e:
                raise serializers.ValidationError({"add_user_ids": f"Invalid UUID: {e}"})

            # Bulk fetch users
            users = list(User.objects.filter(id__in=unique_ids))
            found_ids = {u.id for u in users}
            missing_ids = unique_ids - found_ids

            if missing_ids:
                errors["add_user_ids"] = [
                    f"User with this id : {uid} does not exist." for uid in missing_ids
                ]

            existing_ids = set(
                instance.users.filter(id__in=found_ids).values_list("id", flat=True)
            )
            if existing_ids:
                errors.setdefault("add_user_ids", []).extend(
                    [f"User with this id: {uid} is already in the team." for uid in existing_ids]
                )

            # If no errors, add valid users
            if not errors.get("add_user_ids"):
                instance.users.add(*users)

        # 3. Raise errors if any
        if errors:
            raise serializers.ValidationError(errors)

        # 4. Save
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
            {"id": str(user.id), "name":user.first_name ,"user email": user.username}
            for user in obj.users.all()
        ]


