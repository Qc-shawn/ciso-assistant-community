from rest_framework.routers import DefaultRouter
from .views import (
    CommitteeViewSet, CommitteeMemberViewSet, CommitteeMeetingViewSet,
    CommitteeDecisionViewSet, CommitteeGRCLinkViewSet, CommitteeDocumentViewSet, CommitteeDocumentReviewViewSet
)

router = DefaultRouter()
router.register(r'committees', CommitteeViewSet, basename='committee')
router.register(r'committee-members', CommitteeMemberViewSet, basename='committee-member')
router.register(r'committee-meetings', CommitteeMeetingViewSet, basename='committee-meeting')
router.register(r'committee-decisions', CommitteeDecisionViewSet, basename='committee-decision')
router.register(r'committee-grc-links', CommitteeGRCLinkViewSet, basename='committee-grc-link')
router.register(r'committee-documents', CommitteeDocumentViewSet, basename='committee-document')
router.register(r'committee-document-reviews', CommitteeDocumentReviewViewSet, basename='committee-document-review')

urlpatterns = router.urls
