import knox.views as knox_views
from django.urls import include, path

from iam.views import(
    RoleCreateView, 
    PermissionGroupsView,
    RoleUpdateView,
    RoleListView,
    )

from .views import (
    AuthTokenDetailView,
    PersonalAccessTokenViewSet,
    ChangePasswordView,
    CurrentUserView,
    LoginView,
    PasswordResetView,
    ResetPasswordConfirmView,
    SessionTokenView,
    SetPasswordView,
    TeamCreateView,
    TeamUpdateView,
    TeamDeleteView,
    TeamListView,
    RemoveTeamMemberView
)

urlpatterns = [
    path(r"login/", LoginView.as_view(), name="knox_login"),
    path(r"logout/", knox_views.LogoutView.as_view(), name="knox_logout"),
    path(r"logoutall/", knox_views.LogoutAllView.as_view(), name="knox_logoutall"),
    path("current-user/", CurrentUserView.as_view(), name="current-user"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("password-reset/", PasswordResetView.as_view(), name="password-reset"),
    path(
        "password-reset/confirm/",
        ResetPasswordConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path("set-password/", SetPasswordView.as_view(), name="set-password"),
    path("sso/", include("iam.sso.urls")),
    path(
        "session-token/",
        SessionTokenView.as_view(),
        name="session-token",
    ),
    path("auth-tokens/", PersonalAccessTokenViewSet.as_view(), name="auth-tokens"),
    path(
        "auth-tokens/<str:pk>/",
        AuthTokenDetailView.as_view(),
        name="auth-token-detail",
    ),
    
    # ================================ CUSTOM ROLES ========================
    path("custom-role/", RoleCreateView.as_view(), name="custom-role"),
    path("available-permissions/", PermissionGroupsView.as_view(), name="available-permissions"),
    path("custom-role/list/", RoleListView.as_view(), name="custom-role-list"),
    # path("custom-role/<uuid:id>/", RoleUpdateView.as_view(), name="custom-role-update"),
    
    # =============================== TEAM ================================
    path('teams/create/', TeamCreateView.as_view(), name='create-team'),
    path('teams/<uuid:id>/update/', TeamUpdateView.as_view(), name='team-update'),
    path('teams/<uuid:id>/delete/', TeamDeleteView.as_view(), name='team-delete'),
    path("teams/<uuid:team_id>/members/<uuid:user_id>/remove/", RemoveTeamMemberView.as_view(), name="remove_team_member"),
    path('teams/', TeamListView.as_view(), name='team-list'),
    # =============================== x ====================================

]
