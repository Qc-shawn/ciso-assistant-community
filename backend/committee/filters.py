import django_filters as df
from django.db import models
from .models import Committee, CommitteeMember, CommitteeMeeting, CommitteeDecision, CommitteeDocument, CommitteeDocumentReview
from core.models import DocumentCentre
from iam.models import User

class CommitteeFilter(df.FilterSet):
    """Filter for Committee"""
    
    committee_type = df.MultipleChoiceFilter(
        choices=Committee.CommitteeType.choices
    )
    status = df.MultipleChoiceFilter(
        choices=Committee.Status.choices
    )
    duration_type = df.MultipleChoiceFilter(
        choices=Committee.DurationType.choices
    )
    establishment_date = df.DateFromToRangeFilter()
    
    # For filtering by linked documents
    linked_documents = df.ModelMultipleChoiceFilter(
        field_name='linked_documents__id',  # Note the __id
        queryset=DocumentCentre.objects.all(),
        label="Linked Documents"
    )
    
    search = df.CharFilter(method='filter_search')
    
    class Meta:
        model = Committee
        fields = [
            'committee_type', 'status', 'duration_type',
            'meeting_frequency', 'voting_rule', 'linked_documents'
        ]
    
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            models.Q(name_en__icontains=value) |
            models.Q(name_ar__icontains=value) |
            models.Q(purpose__icontains=value)
        )


class CommitteeMemberFilter(df.FilterSet):
    """Filter for Committee Members"""
    
    role = df.MultipleChoiceFilter(
        choices=CommitteeMember.Role.choices
    )
    membership_status = df.MultipleChoiceFilter(
        choices=CommitteeMember.MembershipStatus.choices
    )
    voting_rights = df.BooleanFilter()
    
    class Meta:
        model = CommitteeMember
        fields = ['committee', 'role', 'membership_status', 'voting_rights']


class CommitteeMeetingFilter(df.FilterSet):
    """Filter for Committee Meetings"""
    
    status = df.MultipleChoiceFilter(
        choices=CommitteeMeeting.Status.choices
    )
    mode = df.MultipleChoiceFilter(
        choices=CommitteeMeeting.MeetingMode.choices
    )
    start_datetime = df.DateTimeFromToRangeFilter()
    
    class Meta:
        model = CommitteeMeeting
        fields = ['committee', 'status', 'mode']


class CommitteeDocumentFilter(df.FilterSet):
    """
    FilterSet for CommitteeDocument
    """
    
    committee = df.ModelMultipleChoiceFilter(
        queryset=Committee.objects.all(),
        field_name='committee__id',
        to_field_name='id'
    )
    
    meeting = df.ModelMultipleChoiceFilter(
        queryset=CommitteeMeeting.objects.all(),
        field_name='meeting__id',
        to_field_name='id'
    )
    
    document_type = df.MultipleChoiceFilter(
        choices=CommitteeDocument.DocumentType.choices
    )
    
    status = df.MultipleChoiceFilter(
        choices=CommitteeDocument.Status.choices
    )
    
    created_by = df.ModelMultipleChoiceFilter(
        queryset=User.objects.all()
    )
    
    # Text search
    search = df.CharFilter(method='filter_search')
    
    # Date ranges
    created_at = df.DateFromToRangeFilter()
    updated_at = df.DateFromToRangeFilter()
    review_date = df.DateFromToRangeFilter()
    approved_date = df.DateFromToRangeFilter()
    expiry_date = df.DateFromToRangeFilter()
    
    # Boolean filters
    is_current = df.BooleanFilter()
    has_attachment = df.BooleanFilter(method='filter_has_attachment')
    
    class Meta:
        model = CommitteeDocument
        fields = [
            'committee',
            'meeting',
            'document_type',
            'status',
            'created_by',
            'is_current',
            'version',
            'review_date',
            'approved_date',
            'expiry_date',
            'created_at',
            'updated_at',
        ]
    
    def filter_search(self, queryset, name, value):
        """Search across multiple text fields"""
        return queryset.filter(
            models.Q(title__icontains=value) |
            models.Q(description__icontains=value) |
            models.Q(notes__icontains=value) |
            models.Q(file_name__icontains=value)
        )
    
    def filter_has_attachment(self, queryset, name, value):
        """Filter by presence of attachment"""
        if value:
            return queryset.exclude(attachment__isnull=True).exclude(attachment='')
        return queryset.filter(models.Q(attachment__isnull=True) | models.Q(attachment=''))


class CommitteeDocumentReviewFilter(df.FilterSet):
    """
    FilterSet for CommitteeDocumentReview
    """
    
    document = df.ModelMultipleChoiceFilter(
        queryset=CommitteeDocument.objects.all()
    )
    
    reviewer = df.ModelMultipleChoiceFilter(
        queryset=User.objects.all()
    )
    
    status = df.MultipleChoiceFilter(
        choices=CommitteeDocumentReview.ReviewStatus.choices
    )
    
    reviewed_at = df.DateFromToRangeFilter()
    
    class Meta:
        model = CommitteeDocumentReview
        fields = ['document', 'reviewer', 'status', 'reviewed_at']