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
        child=serializers.CharField(), required=False
    )
    def validate_name(self, value):
        from iam.models import Role
        if Role.objects.filter(name=value).exists():
            raise serializers.ValidationError("A role with this name already exists.")
        return value

    def validate_permissions(self, value):
        from django.contrib.auth.models import Permission
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

class RoleUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(required=True)
    permissions = serializers.ListField(
        child=serializers.CharField(), required=True, write_only=True
    )

    def validate_permissions(self, value):
        invalid = [p for p in value if not Permission.objects.filter(codename=p).exists()]
        if invalid:
            raise serializers.ValidationError(f"Invalid permissions: {invalid}")
        return value

    def update(self, instance, validated_data):
        from iam.models import UserGroup, RoleAssignment
        from django.contrib.auth.models import Permission

        old_name = instance.name
        new_name = validated_data["name"]

        # 1. Update the role name and permissions
        instance.name = new_name
        instance.save()
        perms = Permission.objects.filter(codename__in=validated_data["permissions"])
        instance.permissions.set(perms)

        # 2. Find all folders for old_name groups
        user_groups = UserGroup.objects.filter(name=old_name)
        for old_group in user_groups:
            # Try to find a group with new_name in this folder
            try:
                new_group = UserGroup.objects.get(name=new_name, folder=old_group.folder)
                if new_group.id != old_group.id:
                    # Merge users
                    if hasattr(old_group, 'users') and hasattr(new_group, 'users'):
                        for user in old_group.users.all():
                            new_group.users.add(user)
                    # Move assignments to new_group
                    for ra in RoleAssignment.objects.filter(user_group=old_group):
                          # Check for duplicate assignment in new_group (same user, same role)
                          exists = RoleAssignment.objects.filter(
                              user_group=new_group,
                              user=ra.user,  # Only if you have a user field
                              role=ra.role
                          )
                          if exists.exists():
                              # Duplicate exists: just delete the old assignment
                              ra.delete()
                          else:
                              ra.user_group = new_group
                              ra.name = new_name
                              ra.save(update_fields=["user_group", "name"])
            except UserGroup.DoesNotExist:
                # No group with new_name: rename old_group
                old_group.name = new_name
                old_group.save()

        # 3. FINAL BULLETPROOF CLEANUP: Remove *any* leftover groups with the old name!
        UserGroup.objects.filter(name=old_name).delete()

        # 4. Update all assignments for this role to the new name
        assignments = RoleAssignment.objects.filter(role=instance)
        for assignment in assignments:
            assignment.name = new_name
            assignment.save(update_fields=["name"])

        return instance

    def to_representation(self, instance):
        return {
            "id": str(instance.id),
            "name": instance.name,
            "permissions": list(instance.permissions.values_list("codename", flat=True)),
        }