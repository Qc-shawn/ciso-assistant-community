from base64 import urlsafe_b64decode
from datetime import timedelta

import logging
import structlog
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.models import Permission
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import ensure_csrf_cookie
from django.db import transaction
from collections import defaultdict

from ciso_assistant.settings import EMAIL_HOST, EMAIL_HOST_RESCUE

from knox import crypto
from knox.auth import TokenAuthentication, get_token_model, knox_settings
from knox.views import DateTimeField
from knox.views import LoginView as KnoxLoginView
from knox.models import AuthToken
from allauth.account.models import EmailAddress

from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from rest_framework import permissions, serializers, status, views
from rest_framework.authtoken.serializers import AuthTokenSerializer
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework import status

from rest_framework.status import (
    HTTP_200_OK,
    HTTP_202_ACCEPTED,
    HTTP_401_UNAUTHORIZED,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from rest_framework.generics import (
    UpdateAPIView,  
    ListAPIView,
    DestroyAPIView,
    GenericAPIView,
    CreateAPIView,
    )

from .models import (
    Folder, 
    PersonalAccessToken, 
    Role, 
    RoleAssignment,
    UserGroup,
    Team
)

from .serializers import (
    ChangePasswordSerializer,
    LoginSerializer,
    PersonalAccessTokenReadSerializer,
    ResetPasswordConfirmSerializer,
    SetPasswordSerializer,
    TeamUpdateSerializer,
    TeamListSerializer,
    RoleCreateSerializer,
    RoleUpdateSerializer, 
    RoleListSerializer,
    TeamCreateSerializer

)

from core.startup import (
    READER_PERMISSIONS_LIST, APPROVER_PERMISSIONS_LIST, ANALYST_PERMISSIONS_LIST,
    DOMAIN_MANAGER_PERMISSIONS_LIST, ADMINISTRATOR_PERMISSIONS_LIST, THIRD_PARTY_RESPONDENT_PERMISSIONS_LIST
)

logger = structlog.get_logger(__name__)

User = get_user_model()
class LoginView(KnoxLoginView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = LoginSerializer

    def post(self, request, format=None):
        serializer = AuthTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        login(request, user)
        return super(LoginView, self).post(request, format=None)
class LogoutView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    @method_decorator(ensure_csrf_cookie)
    def post(self, request) -> Response:
        try:
            logger.info("logout request", user=request.user)
            try:
                auth_header = request.META.get("HTTP_AUTHORIZATION")
                if auth_header and " " in auth_header:
                    access_token = auth_header.split(" ")[1]
                    digest = crypto.hash_token(access_token)
                    auth_token = AuthToken.objects.get(digest=digest)
                    auth_token.delete()
                else:
                    logger.warning(
                        "No valid authorization header found during logout",
                        user=request.user,
                    )
            except Exception as e:
                logger.error(
                    "Error deleting token during logout",
                    user=request.user,
                    error=str(e),
                )
            logout(request)
            logger.info("logout successful", user=request.user)
        except Exception as e:
            logger.error("logout failed", user=request.user, error=e)
        return Response({"message": "Logged out successfully."}, status=HTTP_200_OK)
class PersonalAccessTokenViewSet(views.APIView):
    def get_queryset(self):
        return PersonalAccessToken.objects.filter(auth_token__user=self.request.user)

    def get_context(self):
        return {"request": self.request, "format": self.format_kwarg, "view": self}

    def get_token_prefix(self):
        return knox_settings.TOKEN_PREFIX

    def get_token_limit_per_user(self):
        return 5

    def get_expiry_datetime_format(self):
        return knox_settings.EXPIRY_DATETIME_FORMAT

    def format_expiry_datetime(self, expiry):
        datetime_format = self.get_expiry_datetime_format()
        return DateTimeField(format=datetime_format).to_representation(expiry)

    def create_token(self, expiry):
        token_prefix = self.get_token_prefix()
        return get_token_model().objects.create(
            user=self.request.user, expiry=expiry, prefix=token_prefix
        )

    def get_post_response_data(self, request, token, name, instance):
        data = {
            "name": name,
            "expiry": self.format_expiry_datetime(instance.expiry),
            "token": token,
        }
        return data

    def get_post_response(self, request, token, name, instance):
        data = self.get_post_response_data(request, token, name, instance)
        return Response(data)

    def post(self, request, format=None):
        token_limit_per_user = self.get_token_limit_per_user()
        name = request.data.get("name")
        try:
            expiry_days = int(request.data.get("expiry", 30))
            if expiry_days <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {"error": "Expiry must be a positive integer (days)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if token_limit_per_user is not None:
            now = timezone.now()
            token = request.user.auth_token_set.filter(expiry__gt=now).filter(
                personalaccesstoken__isnull=False
            )
            if token.count() >= token_limit_per_user:
                return Response(
                    {"error": "errorMaxPatAmountExceeded"},
                    status=status.HTTP_403_FORBIDDEN,
                )
        instance, token = self.create_token(timedelta(days=int(expiry_days)))
        pat = PersonalAccessToken.objects.create(auth_token=instance, name=name)
        return self.get_post_response(request, token, pat.name, pat.auth_token)

    def get(self, request, *args, **kwargs):
        """
        Get all personal access tokens for the user.
        """
        queryset = self.get_queryset()
        serializer = PersonalAccessTokenReadSerializer(
            queryset, many=True, context=self.get_context()
        )
        return Response(serializer.data)


class AuthTokenDetailView(views.APIView):
    def delete(self, request, *args, **kwargs):
        try:
            token = AuthToken.objects.get(digest=kwargs["pk"])
            if token.user != request.user:
                return Response(
                    {"error": "You do not have permission to delete this token."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            token.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except AuthToken.DoesNotExist:
            logger.info(
                "Attempt to delete non-existent token",
                digest=kwargs["pk"],
                user=request.user.id,
            )
            return Response(
                {"error": "Token not found or already deleted."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            logger.error(
                "Error deleting token",
                error=str(e),
                digest=kwargs["pk"],
                user=request.user.id,
            )
            return Response(
                {"error": "Failed to delete token due to an internal error."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
class CurrentUserView(views.APIView):
    # Is this condition really necessary if we have permission_classes = [permissions.IsAuthenticated] ?
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request) -> Response:
        if not request.user.is_authenticated:
            return Response(
                {"error": "You are not logged in. Please ensure you are logged in."},
                status=HTTP_401_UNAUTHORIZED,
            )
        accessible_domains = RoleAssignment.get_accessible_folders(
            Folder.get_root_folder(), request.user, Folder.ContentType.DOMAIN
        )
        res_data = {
            "id": request.user.id,
            "email": request.user.email,
            "first_name": request.user.first_name,
            "last_name": request.user.last_name,
            "is_active": request.user.is_active,
            "date_joined": request.user.date_joined,
            "user_groups": request.user.get_user_groups(),
            "roles": request.user.get_roles(),
            "permissions": request.user.permissions,
            "is_third_party": request.user.is_third_party,
            "is_admin": request.user.is_admin(),
            "is_local": request.user.is_local,
            "accessible_domains": [str(f) for f in accessible_domains],
            "domain_permissions": RoleAssignment.get_permissions_per_folder(
                principal=request.user, recursive=True
            ),
            "root_folder_id": Folder.get_root_folder().id,
            "preferences": request.user.preferences,
        }
        return Response(res_data, status=HTTP_200_OK)


class SessionTokenView(views.APIView):
    """
    API Endpoint for getting the session token from an access token
    This is needed for allauth's authentication flows.
    """

    def post(self, request):
        access_token = request.META.get("HTTP_AUTHORIZATION").split(" ")[1]
        if not access_token:
            return Response(
                {"error": "No access token provided"}, status=HTTP_401_UNAUTHORIZED
            )
        # Get user from token
        auth = TokenAuthentication()
        user, _ = auth.authenticate_credentials(access_token.encode())
        if not user:
            return Response(
                {"error": "Invalid access token"}, status=HTTP_401_UNAUTHORIZED
            )
        # Log the user in and get the session token
        # This token is used for allauth's authentication flows
        login(request, user)
        session_token = request.session.session_key
        return Response({"token": session_token})


class PasswordResetView(views.APIView):
    permission_classes = [permissions.AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def post(self, request):
        email = request.data["email"]  # type: ignore
        associated_user = User.objects.filter(email=email).first()
        if EMAIL_HOST or EMAIL_HOST_RESCUE:
            if associated_user is not None and associated_user.is_local:
                try:
                    associated_user.mailing(
                        email_template_name="registration/password_reset_email.html",
                        subject=_("CISO Assistant: Password Reset"),
                    )
                    print("Sending reset mail to", email)
                except Exception as e:
                    print(e)
            return Response(status=HTTP_202_ACCEPTED)
        return Response(
            data={
                "error": "Email server not configured, please contact your administrator"
            },
            status=HTTP_500_INTERNAL_SERVER_ERROR,
        )


class ResetPasswordConfirmView(views.APIView):
    """
    API Endpoint for reset password confirm
    """

    default_token_generator = PasswordResetTokenGenerator()
    permission_classes = [permissions.AllowAny]
    serialier_class = ResetPasswordConfirmSerializer
    token_generator = default_token_generator

    def get_user(self, uidb64):
        try:
            # urlsafe_base64_decode() decodes to bytestring
            uid = urlsafe_b64decode(uidb64).decode()
            user = User.objects.get(pk=uid)
        except (
            TypeError,
            ValueError,
            OverflowError,
            User.DoesNotExist,
        ):
            user = None
        return user

    @method_decorator(ensure_csrf_cookie)
    def post(self, request, *args, **kwargs):
        serializer = ResetPasswordConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uidb64 = serializer.validated_data.get("uidb64")
        token = serializer.validated_data.get("token")
        new_password = serializer.validated_data.get("new_password")
        user = self.get_user(uidb64)
        if (
            user is not None and user.is_local
        ):  # Only local user can reset their password.
            if self.token_generator.check_token(user, token):
                user.set_password(new_password)
                user.save()
                return Response(status=status.HTTP_200_OK)
        return Response(
            data={"error": "The link is invalid or has expired."},
            status=status.HTTP_400_BAD_REQUEST,
        )


class ChangePasswordView(views.APIView):
    """
    An endpoint for changing password.
    """

    permission_classes = (permissions.IsAuthenticated,)

    serializer_class = ChangePasswordSerializer

    def post(self, request, *args, **kwargs):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = self.request.user
        old_password = serializer.validated_data.get("old_password")
        new_password = serializer.validated_data.get("new_password")
        if not user.check_password(old_password):
            raise serializers.ValidationError(
                "Your old password was entered incorrectly. Please enter it again."
            )
        user.set_password(new_password)
        user.save()
        return Response(status=status.HTTP_200_OK)


class SetPasswordView(views.APIView):
    """
    An endpoint for setting a password as an administrator.
    """

    permission_classes = (permissions.IsAuthenticated,)

    serializer_class = SetPasswordSerializer

    def post(self, request, *args, **kwargs):
        serializer = SetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if RoleAssignment.has_role(
            self.request.user, Role.objects.get(name="BI-RL-ADM")
        ):
            new_password = serializer.validated_data.get("new_password")
            user = serializer.validated_data.get("user")
            user.set_password(new_password)
            user.save()
            try:
                email_address = EmailAddress.objects.get(user=user, primary=True)
                email_address.verified = True
                email_address.save()
            except Exception as e:
                logger.error(
                    "Error setting email address as verified",
                    user=user,
                    error=e,
                )
            return Response(status=status.HTTP_200_OK)
        return Response(status=status.HTTP_401_UNAUTHORIZED)

# ---------------------------------------------------- CUSTOM ROLES VIEWS----------------------------------------------------

# class RoleCreateView(GenericAPIView):
#     serializer_class = RoleCreateSerializer
#     @swagger_auto_schema(
#         operation_description="Create a new role, assign permissions, and auto-generate user groups and role assignments for all folders.",
#         request_body=RoleCreateSerializer,
#         responses={201: openapi.Response("Role created")},
#     )
#     def post(self, request):
#         serializer = self.get_serializer(data=request.data)
#         serializer.is_valid(raise_exception=True)
    
#         from iam.models import Folder, Role, UserGroup, RoleAssignment
    
#         # 1) Create the Role
#         role = Role.objects.create(
#             name=serializer.validated_data["name"],
#             builtin=False,
#             is_published=True
#         )
    
#         # 2) Assign Permissions (validated to a queryset)
#         permissions = serializer.validated_data.get("permissions")
#         if permissions:
#             role.permissions.set(permissions)
    
#         # 2b) Persist the scope on the role so future domains behave correctly
#         apply_all   = serializer.validated_data.get("apply_to_all_companies", False)
#         select_some = serializer.validated_data.get("select_specific_companies", False)
#         role.auto_apply_to_new_companies = bool(apply_all)
#         role.save(update_fields=["auto_apply_to_new_companies"])
    
#         # 3) Optional scope: create UserGroups + RoleAssignments
#         root = Folder.get_root_folder()
#         company_ids = serializer.validated_data.get("company_ids") or []
#         created_assignments = []
    
#         # Determine target companies (Folders with content_type=DOMAIN)
#         companies_qs = None
#         if apply_all:
#             companies_qs = Folder.objects.filter(content_type=Folder.ContentType.DOMAIN)
#         elif select_some:
#             companies_qs = Folder.objects.filter(
#                 id__in=company_ids,
#                 content_type=Folder.ContentType.DOMAIN
#             )
    
#         # --- Per-company assignments ---
#         if companies_qs is not None:
#             for company in companies_qs:
#                 group, _ = UserGroup.objects.get_or_create(
#                     name=role.name,
#                     folder=company,
#                     defaults={"builtin": False}
#                 )
#                 ra, _ = RoleAssignment.objects.get_or_create(
#                     user_group=group,
#                     role=role,
#                     folder=root,
#                     defaults={"is_recursive": True},
#                 )
#                 ra.perimeter_folders.add(company)
#                 ra.is_recursive = True
#                 ra.name = role.name
#                 ra.save(update_fields=["is_recursive", "name"])
    
#                 created_assignments.append({
#                     "company_id": str(company.id),
#                     "company": company.name,
#                     "user_group": group.name
#                 })
    
#         # --- Global assignment (always runs if apply_all=True) ---
#         if apply_all:
#             try:
#                 global_folder = Folder.objects.get(content_type=Folder.ContentType.ROOT)
    
#                 group, _ = UserGroup.objects.get_or_create(
#                     name=role.name,
#                     folder=global_folder,
#                     defaults={"builtin": False}
#                 )
    
#                 ra, _ = RoleAssignment.objects.get_or_create(
#                     user_group=group,
#                     role=role,
#                     folder=global_folder,
#                     defaults={"is_recursive": True},
#                 )
#                 ra.perimeter_folders.set([global_folder])
#                 ra.is_recursive = True
#                 ra.name = role.name
#                 ra.save(update_fields=["is_recursive", "name"])
    
#                 created_assignments.append({
#                     "company_id": str(global_folder.id),
#                     "company": global_folder.name,
#                     "user_group": group.name
#                 })
#             except Folder.DoesNotExist:
#                 pass
            
#         # 4) Response
#         return Response(
#             {
#                 "id": str(role.id),
#                 "name": role.name,
#                 "permissions": list(role.permissions.values_list("codename", flat=True)),
#                 "assignments_created": created_assignments,
#             },
#             status=status.HTTP_201_CREATED
#         )

logger = logging.getLogger(__name__)

class RoleCreateView(GenericAPIView):
    serializer_class = RoleCreateSerializer
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Create a new role, assign permissions, and generate user groups and role assignments.",
        request_body=RoleCreateSerializer,
        responses={201: openapi.Response("Role created")},
    )
    @transaction.atomic
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        apply_all   = serializer.validated_data.get("apply_to_all_companies", False)
        select_some = serializer.validated_data.get("select_specific_companies", False)
        company_ids = serializer.validated_data.get("company_ids") or []

        # Validation: ensure consistency
        if select_some and not company_ids:
            return Response(
                {"detail": "Must provide company_ids when select_specific_companies=True"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 1) Create the Role
        role = Role.objects.create(
            name=serializer.validated_data["name"],
            builtin=False,
            is_published=True,
            auto_apply_to_new_companies=bool(apply_all)
        )

        # 2) Assign Permissions
        permissions = serializer.validated_data.get("permissions")
        if permissions:
            role.permissions.set(permissions)

        root = Folder.get_root_folder()
        created_assignments = []

        # 3) Determine companies
        companies_qs = None
        if apply_all:
            companies_qs = Folder.objects.filter(content_type=Folder.ContentType.DOMAIN)
        elif select_some:
            companies_qs = Folder.objects.filter(
                id__in=company_ids,
                content_type=Folder.ContentType.DOMAIN
            )

        if companies_qs is not None:
            for company in companies_qs:
                group, _ = UserGroup.objects.get_or_create(
                    name=role.name,
                    folder=company,
                    defaults={"builtin": False}
                )
                ra, _ = RoleAssignment.objects.get_or_create(
                    user_group=group,
                    role=role,
                    folder=root,
                    defaults={"is_recursive": True},
                )
                ra.perimeter_folders.add(company)
                ra.is_recursive = True
                ra.name = role.name
                ra.save(update_fields=["is_recursive", "name"])

                created_assignments.append({
                    "company_id": str(company.id),
                    "company": company.name,
                    "user_group": group.name
                })

        # 4) Global assignment (if apply_all=True)
        if apply_all:
            try:
                global_folder = Folder.objects.get(content_type=Folder.ContentType.ROOT)
                group, _ = UserGroup.objects.get_or_create(
                    name=role.name,
                    folder=global_folder,
                    defaults={"builtin": False}
                )
                ra, _ = RoleAssignment.objects.get_or_create(
                    user_group=group,
                    role=role,
                    folder=global_folder,
                    defaults={"is_recursive": True},
                )
                ra.perimeter_folders.set([global_folder])
                ra.is_recursive = True
                ra.name = role.name
                ra.save(update_fields=["is_recursive", "name"])

                created_assignments.append({
                    "company_id": str(global_folder.id),
                    "company": global_folder.name,
                    "user_group": group.name
                })
            except Folder.DoesNotExist:
                logger.warning("Global root folder not found during role creation.")

        # 5) Audit log
        logger.info(
            "Role '%s' (id=%s) created by user=%s with %d assignments.",
            role.name, role.id, request.user.username, len(created_assignments)
        )

        # 6) Response
        return Response(
            {
                "id": str(role.id),
                "name": role.name,
                "permissions": list(role.permissions.values_list("codename", flat=True)),
                "assignments_created": created_assignments,
            },
            status=status.HTTP_201_CREATED
        )

# ------------------------------------------------PERMISSIONS------------------------------------------------

PARENT_MAPPING = {
    # "overview": [
    #     "analytics", "myassignments"   # frontend-only, no Django perms
    # ],

    "organization": [
        "folder", "perimeter", "user",
        "usergroup", "roleassignment"
    ],

    "catalog": [
        "framework", "threat", "referencecontrol",
        "requirementmapping", "requirementmappingset",
        "requirementnode", "riskmatrix"
    ],

    "assetsManagement": [
        "asset", "businessimpactanalysis",
        "assetassessment", "escalationthreshold", "assetclass"
    ],

    "operations": [
        # "calendar", "xray",
        "appliedcontrol", 
        "incident", "timelineentry", "tasknode", "tasktemplate"
    ],

    "governance": [
        "loadedlibrary", "storedlibrary",
        "policy", "riskacceptance",
        "securityexception", "finding", "findingsassessment"
    ],

    "risk": [
        "riskassessment", "ebiosrmstudy", "riskscenario",
        "fearedevent", "roto", "stakeholder", "strategicscenario",
        "attackpath", "operationalscenario", "qualification", "vulnerability"
    ],

    "compliance": [
        "complianceassessment", "evidence", "campaign"
    ],

    "thirdPartyCategory": [
        "entity", "entityassessment", "representative", "solution"
    ],

    "privacy": [
        "processing", "processingnature", "purpose",
        "personaldata", "datasubject", "datarecipient",
        "datacontractor", "datatransfer"
    ],

    "extra": [
        "globalsettings", "ssosettings",
        "filteringlabel",
        "event", "logentry",
        # "backuprestore", "auditlog" 
    ],

    "insight": [
        # frontend-only, no Django perms
    ]
}
class PermissionGroupsView(APIView):
    """
    Return all permissions grouped by parent/child screen.
    Extra permissions (not tied to any known screen) are listed under 'extra_permissions'.
    """

    def get(self, request):
        response = defaultdict(dict)
        extras = []

        try:
            permissions = list(Permission.objects.values_list("codename", flat=True))
        except Exception as e:
            logger.error(f"Failed to fetch permissions: {e}")
            permissions = []

        matched = set()

        for parent, children in PARENT_MAPPING.items():
            response[parent] = {}

            for child in children:
                try:
                    child_key = child.lower().strip()
                    child_perms = []

                    for p in permissions:
                        if not p or "_" not in p:
                            continue
                        try:
                            _, model = p.split("_", 1)
                        except ValueError:
                            continue

                        if model == child_key:
                            child_perms.append(p)
                            matched.add(p)

                    response[parent][child] = sorted(set(child_perms))

                except Exception as e:
                    logger.error(f"Error processing child '{child}' in '{parent}': {e}")
                    response[parent][child] = []

        # Collect extra permissions not mapped to any child
        for p in permissions:
            if p not in matched:
                extras.append(p)

        if extras:
            response["extra_permissions"] = sorted(set(extras))

        return Response(dict(response))

# ------------------------------------------------ UPDATE ROLE ------------------------------------------------

class RoleUpdateView(UpdateAPIView):
    queryset = Role.objects.all()
    serializer_class = RoleUpdateSerializer
    lookup_field = "id"
    http_method_names = ['put']

    def get_object(self):
        return Role.objects.get(id=self.kwargs['id'])

# ------------------------------------------------ XXXXXXXXXXXXXX ------------------------------------------------
class RoleListView(ListAPIView):
    queryset = Role.objects.filter(builtin=False)
    serializer_class = RoleListSerializer
    pagination_class = None  # Optional

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        return Response({"custom-roles": serializer.data})
    
    
# ------------------------------------------------ TEAM VIEW ------------------------------------------------
class TeamCreateView(CreateAPIView):
    queryset = Team.objects.all()
    serializer_class = TeamCreateSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        team = serializer.save()
        users = team.users.all()
        return Response({
            "team_id": team.id,
            "team_name": team.name,
            "users": [
                {"id": user.id, "username": user.username}
                for user in users
            ]
        }, status=status.HTTP_201_CREATED)

# ------------------------------------------------ UPDATE TEAM VIEW ------------------------------------------------
from django.shortcuts import get_object_or_404
class TeamUpdateView(UpdateAPIView):
    queryset = Team.objects.all()
    serializer_class = TeamUpdateSerializer
    lookup_field = "id"
    permission_classes = [IsAuthenticated]

    def update(self, request, *args, **kwargs):
        # 1. Ensure team exists
        team = get_object_or_404(Team, id=kwargs.get("id"))

        # 2. Run serializer validation
        serializer = self.get_serializer(team, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        # 3. Apply changes
        team = serializer.save()

        # 4. Build consistent response
        return Response(
            {
                "team_id": str(team.id),
                "team_name": team.name,
                "users": [
                    {"id": str(user.id),"name":user.first_name ,"email": user.username}
                    for user in team.users.all()
                ],
            },
            status=status.HTTP_200_OK,
        )
    
# -------------------------------------------------- TEAM DELETE VIEW ------------------------------------------------
class TeamDeleteView(DestroyAPIView):
    queryset = Team.objects.all()
    lookup_field = "id" 
    permission_classes = [IsAuthenticated]
    
    def delete(self, request, *args, **kwargs):
        team = self.get_object()
        team_id = str(team.id)
        team.delete()
        return Response(
            {"message": f"Team {team_id} deleted."},
            status=status.HTTP_204_NO_CONTENT
        )
# ---------------------------------------------------- TEAM LIST VIEW ------------------------------------------------
class TeamListView(ListAPIView):
    queryset = Team.objects.all()
    serializer_class = TeamListSerializer

