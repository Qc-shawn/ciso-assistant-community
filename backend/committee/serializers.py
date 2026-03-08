import uuid
import os
from django.db import transaction
from rest_framework import serializers
from django.utils import timezone
from core.models import DocumentCentre, Perimeter, Folder
from iam.models import User
from core.serializers import BaseModelSerializer, FieldsRelatedField, CustomDateField, PathField
from .models import (
    Committee, CommitteeMember, CommitteeMeeting, 
    CommitteeMeetingAttendance, CommitteeDecision, CommitteeGRCLink, CommitteeDocument, CommitteeDocumentReview
)

class CommitteeWriteSerializer(BaseModelSerializer):
    """Serializer for creating/updating committees"""
    
    establishment_date = CustomDateField()
    end_date = CustomDateField(required=False, allow_null=True)
    
    perimeter = serializers.PrimaryKeyRelatedField(
        queryset=Perimeter.objects.all(),
        required=False,
        allow_null=True
    )
    
    default_secretary = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
        allow_null=True
    )
    
    decision_authority = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
        allow_null=True
    )
    
    agenda_template = serializers.PrimaryKeyRelatedField(
        queryset=DocumentCentre.objects.all(),
        required=False,
        allow_null=True
    )
    
    def validate(self, attrs):
        """Validate committee data"""
        # If temporary, end date is required
        if attrs.get('duration_type') == Committee.DurationType.TEMPORARY:
            if not attrs.get('end_date'):
                raise serializers.ValidationError({
                    'end_date': 'End date is required for temporary committees'
                })
        
        return attrs
    
    class Meta:
        model = Committee
        exclude = ['created_at', 'updated_at', 'is_published']
        read_only_fields = ['created_by', 'updated_by']


class CommitteeReadSerializer(CommitteeWriteSerializer):
    """Serializer for reading committees with expanded relationships"""
    
    path = PathField(read_only=True)
    folder = FieldsRelatedField()
    perimeter = FieldsRelatedField()
    
    committee_type = serializers.CharField(source='get_committee_type_display')
    status = serializers.CharField(source='get_status_display')
    duration_type = serializers.CharField(source='get_duration_type_display')
    voting_rule = serializers.CharField(source='get_voting_rule_display')
    meeting_frequency = serializers.CharField(source='get_meeting_frequency_display')
    default_meeting_mode = serializers.CharField(source='get_default_meeting_mode_display')
    
    default_secretary = FieldsRelatedField(fields=['id', 'first_name', 'last_name', 'email'])
    decision_authority = FieldsRelatedField(fields=['id', 'first_name', 'last_name', 'email'])
    agenda_template = FieldsRelatedField(fields=['id', 'document_name', 'document_type'])
    
    # Add source parameter to explicitly tell it where to get the data
    # linked_documents = serializers.StringRelatedField(many=True)
    
    # Computed fields
    current_members_count = serializers.IntegerField(read_only=True)
    required_quorum = serializers.IntegerField(read_only=True)
    meetings_count = serializers.SerializerMethodField()
    
    def get_meetings_count(self, obj):
        return obj.meetings.count()
    
    class Meta:
        model = Committee
        fields = "__all__"


class CommitteeMemberWriteSerializer(BaseModelSerializer):
    """Serializer for committee members"""
    
    joining_date = CustomDateField()
    
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all()
    )
    committee = serializers.PrimaryKeyRelatedField(
        queryset=Committee.objects.all()
    )
    alternate_member = serializers.PrimaryKeyRelatedField(
        queryset=CommitteeMember.objects.all(),
        required=False,
        allow_null=True
    )
    
    def validate(self, attrs):
        """Validate member data"""
        # Can't be alternate to yourself
        if attrs.get('alternate_member') and attrs.get('alternate_member') == self.instance:
            raise serializers.ValidationError({
                'alternate_member': 'Member cannot be alternate to themselves'
            })
        
        # Only one chairperson per committee
        if attrs.get('role') == CommitteeMember.Role.CHAIRPERSON:
            committee = attrs.get('committee') or (self.instance.committee if self.instance else None)
            existing_chair = CommitteeMember.objects.filter(
                committee=committee,
                role=CommitteeMember.Role.CHAIRPERSON,
                membership_status='active'
            ).exclude(id=self.instance.id if self.instance else None).exists()
            
            if existing_chair:
                raise serializers.ValidationError({
                    'role': 'This committee already has an active chairperson'
                })
        
        return attrs
    
    class Meta:
        model = CommitteeMember
        exclude = ['created_at', 'updated_at', 'is_published']


class CommitteeMemberReadSerializer(CommitteeMemberWriteSerializer):
    """Serializer for reading committee members"""
    
    committee = FieldsRelatedField(fields=['id', 'name_en', 'committee_type'])
    user = FieldsRelatedField(fields=['id', 'first_name', 'last_name', 'email'])
    role = serializers.CharField(source='get_role_display')
    membership_status = serializers.CharField(source='get_membership_status_display')
    alternate_member = FieldsRelatedField(fields=['id', 'user'])
    
    class Meta:
        model = CommitteeMember
        fields = "__all__"


class CommitteeMeetingWriteSerializer(BaseModelSerializer):
    """Serializer for committee meetings"""
    
    start_datetime = serializers.DateTimeField()
    end_datetime = serializers.DateTimeField()
    
    committee = serializers.PrimaryKeyRelatedField(
        queryset=Committee.objects.all()
    )
    secretary = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
        allow_null=True
    )
    agenda_document = serializers.PrimaryKeyRelatedField(
        queryset=DocumentCentre.objects.all(),
        required=False,
        allow_null=True
    )
    minutes_document = serializers.PrimaryKeyRelatedField(
        queryset=DocumentCentre.objects.all(),
        required=False,
        allow_null=True
    )
    
    def validate(self, attrs):
        """Validate meeting data"""
        if attrs.get('end_datetime') and attrs.get('start_datetime'):
            if attrs['end_datetime'] <= attrs['start_datetime']:
                raise serializers.ValidationError({
                    'end_datetime': 'End time must be after start time'
                })
        
        return attrs
    
    class Meta:
        model = CommitteeMeeting
        exclude = ['created_at', 'updated_at', 'is_published']


class CommitteeMeetingReadSerializer(CommitteeMeetingWriteSerializer):
    """Serializer for reading committee meetings"""
    
    committee = FieldsRelatedField(fields=['id', 'name_en', 'committee_type'])
    status = serializers.CharField(source='get_status_display')
    mode = serializers.CharField(source='get_mode_display')
    secretary = FieldsRelatedField(fields=['id', 'first_name', 'last_name', 'email'])
    agenda_document = FieldsRelatedField(fields=['id', 'document_name'])
    minutes_document = FieldsRelatedField(fields=['id', 'document_name'])
    
    # Attendance summary
    attendance_summary = serializers.SerializerMethodField()
    
    def get_attendance_summary(self, obj):
        attendance = obj.attendance.all()
        return {
            'total_members': obj.committee.current_members_count,
            'attended': attendance.filter(status='attended').count(),
            'absent': attendance.filter(status='absent').count(),
            'excused': attendance.filter(status='excused').count(),
        }
    
    class Meta:
        model = CommitteeMeeting
        fields = "__all__"


class CommitteeMeetingAttendanceWriteSerializer(BaseModelSerializer):
    """Serializer for meeting attendance"""
    
    meeting = serializers.PrimaryKeyRelatedField(
        queryset=CommitteeMeeting.objects.all()
    )
    member = serializers.PrimaryKeyRelatedField(
        queryset=CommitteeMember.objects.all()
    )
    represented_by = serializers.PrimaryKeyRelatedField(
        queryset=CommitteeMember.objects.all(),
        required=False,
        allow_null=True
    )
    
    class Meta:
        model = CommitteeMeetingAttendance
        exclude = ['created_at', 'updated_at', 'is_published']


class CommitteeMeetingAttendanceReadSerializer(CommitteeMeetingAttendanceWriteSerializer):
    """Serializer for reading meeting attendance"""
    
    meeting = FieldsRelatedField(fields=['id', 'title', 'start_datetime'])
    member = FieldsRelatedField(fields=['id', 'user'])
    status = serializers.CharField(source='get_status_display')
    represented_by = FieldsRelatedField(fields=['id', 'user'])
    
    class Meta:
        model = CommitteeMeetingAttendance
        fields = "__all__"


class CommitteeDecisionWriteSerializer(BaseModelSerializer):
    """Serializer for committee decisions"""
    
    effective_date = CustomDateField(required=False, allow_null=True)
    
    meeting = serializers.PrimaryKeyRelatedField(
        queryset=CommitteeMeeting.objects.all()
    )
    supporting_document = serializers.PrimaryKeyRelatedField(
        queryset=DocumentCentre.objects.all(),
        required=False,
        allow_null=True
    )
    
    class Meta:
        model = CommitteeDecision
        exclude = ['created_at', 'updated_at', 'is_published']


class CommitteeDecisionReadSerializer(CommitteeDecisionWriteSerializer):
    """Serializer for reading committee decisions"""
    
    meeting = FieldsRelatedField(fields=['id', 'title', 'start_datetime'])
    status = serializers.CharField(source='get_status_display')
    supporting_document = FieldsRelatedField(fields=['id', 'document_name'])
    
    class Meta:
        model = CommitteeDecision
        fields = "__all__"


class CommitteeGRCLinkWriteSerializer(BaseModelSerializer):
    """Serializer for GRC links"""
    
    committee = serializers.PrimaryKeyRelatedField(
        queryset=Committee.objects.all()
    )
    linked_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
        allow_null=True
    )
    
    class Meta:
        model = CommitteeGRCLink
        exclude = ['created_at', 'updated_at', 'is_published']
        read_only_fields = ['linked_date']


class CommitteeGRCLinkReadSerializer(CommitteeGRCLinkWriteSerializer):
    """Serializer for reading GRC links"""
    
    committee = FieldsRelatedField(fields=['id', 'name_en'])
    linked_by = FieldsRelatedField(fields=['id', 'first_name', 'last_name'])
    entity_type = serializers.CharField(source='get_entity_type_display')
    
    class Meta:
        model = CommitteeGRCLink
        fields = "__all__"


class CommitteeDocumentWriteSerializer(BaseModelSerializer):
    """
    Serializer for creating/updating committee documents
    """
    
    attachment = serializers.FileField(
        required=False,
        allow_null=True,
        write_only=True
    )
    
    committee = serializers.PrimaryKeyRelatedField(
        queryset=Committee.objects.all(),
        required=True
    )
    
    meeting = serializers.PrimaryKeyRelatedField(
        queryset=CommitteeMeeting.objects.all(),
        required=False,
        allow_null=True
    )
    
    created_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
        allow_null=True
    )
    
    last_modified_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
        allow_null=True
    )
    
    approved_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
        allow_null=True
    )
    
    previous_version = serializers.PrimaryKeyRelatedField(
        queryset=CommitteeDocument.objects.all(),
        required=False,
        allow_null=True
    )
    
    # IMPORTANT: Add folder field
    folder = serializers.PrimaryKeyRelatedField(
        queryset=Folder.objects.all(),
        required=False,
        allow_null=True
    )
    
    review_date = CustomDateField(required=False, allow_null=True)
    approved_date = CustomDateField(required=False, allow_null=True)
    expiry_date = CustomDateField(required=False, allow_null=True)
    
    def validate(self, attrs):
        """Validate that either attachment or link is provided"""
        attachment = attrs.get('attachment')
        link = attrs.get('link')
        
        if not attachment and not link:
            raise serializers.ValidationError(
                "Either attachment or link must be provided"
            )
        
        return attrs
    
    def create(self, validated_data):
        # Set created_by if not provided
        if not validated_data.get('created_by'):
            validated_data['created_by'] = self.context['request'].user
        
        # Set last_modified_by
        validated_data['last_modified_by'] = self.context['request'].user
        
        # CRITICAL FIX: Set folder from committee if not provided
        if not validated_data.get('folder') and validated_data.get('committee'):
            validated_data['folder'] = validated_data['committee'].folder
        
        # Debug output
        print(f"Creating document with folder: {validated_data.get('folder')}")
        
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        # Handle attachment update
        if 'attachment' in validated_data and validated_data['attachment']:
            # If updating attachment, create new version instead
            if instance.attachment:
                new_instance = instance.create_new_version(user=self.context['request'].user)
                new_instance.attachment = validated_data.pop('attachment')
                new_instance.last_modified_by = self.context['request'].user
                new_instance.save()
                return new_instance
        
        # Update last_modified_by
        validated_data['last_modified_by'] = self.context['request'].user
        
        return super().update(instance, validated_data)
    
    class Meta:
        model = CommitteeDocument
        exclude = ['created_at', 'updated_at', 'is_published']
        read_only_fields = ['checksum', 'file_size', 'file_name', 'mime_type', 'page_count']


class CommitteeDocumentReadSerializer(CommitteeDocumentWriteSerializer):
    """
    Serializer for reading committee documents with expanded relationships
    """
    
    path = PathField(read_only=True)
    folder = FieldsRelatedField()
    committee = FieldsRelatedField(fields=['id', 'name_en', 'committee_type'])
    meeting = FieldsRelatedField(fields=['id', 'title', 'start_datetime'])
    
    document_type = serializers.CharField(source='get_document_type_display')
    status = serializers.CharField(source='get_status_display')
    
    created_by = FieldsRelatedField(fields=['id', 'first_name', 'last_name', 'email'])
    last_modified_by = FieldsRelatedField(fields=['id', 'first_name', 'last_name', 'email'])
    approved_by = FieldsRelatedField(fields=['id', 'first_name', 'last_name', 'email'])
    previous_version = FieldsRelatedField(fields=['id', 'title', 'version'])
    
    formatted_file_size = serializers.CharField(read_only=True)
    is_attachment_valid = serializers.BooleanField(read_only=True)
    download_url = serializers.SerializerMethodField()
    
    # Version history
    version_history = serializers.SerializerMethodField()
    
    # Review status
    review_summary = serializers.SerializerMethodField()
    
    def get_download_url(self, obj):
        """Get download URL for attachment"""
        if obj.attachment:
            return obj.attachment.url
        return None
    
    def get_version_history(self, obj):
        """Get all versions of this document"""
        versions = CommitteeDocument.objects.filter(
            committee=obj.committee,
            title=obj.title,
            document_type=obj.document_type
        ).order_by('-version')
        
        return [
            {
                'id': str(v.id),
                'version': v.version,
                'status': v.get_status_display(),
                'created_at': v.created_at,
                'is_current': v.is_current,
                'created_by': {
                    'id': str(v.created_by.id),
                    'name': f"{v.created_by.first_name} {v.created_by.last_name}"
                } if v.created_by else None,
                'file_size': v.formatted_file_size
            }
            for v in versions
        ]
    
    def get_review_summary(self, obj):
        """Get summary of reviews"""
        reviews = obj.reviews.all()
        return {
            'total': reviews.count(),
            'pending': reviews.filter(status='pending').count(),
            'approved': reviews.filter(status='approved').count(),
            'rejected': reviews.filter(status='rejected').count(),
            'changes_requested': reviews.filter(status='changes_requested').count(),
        }
    
    class Meta:
        model = CommitteeDocument
        fields = "__all__"
        read_only_fields = ['created_at', 'updated_at', 'is_published']


class CommitteeDocumentReviewWriteSerializer(BaseModelSerializer):
    """
    Serializer for document reviews
    """
    
    document = serializers.PrimaryKeyRelatedField(
        queryset=CommitteeDocument.objects.all()
    )
    reviewer = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all()
    )
    reviewed_at = serializers.DateTimeField(required=False, allow_null=True)
    
    def validate(self, attrs):
        """Validate review data"""
        # Check if this reviewer already reviewed this document
        document = attrs.get('document')
        reviewer = attrs.get('reviewer')
        
        if document and reviewer:
            existing = CommitteeDocumentReview.objects.filter(
                document=document,
                reviewer=reviewer
            ).exclude(id=self.instance.id if self.instance else None).exists()
            
            if existing:
                raise serializers.ValidationError(
                    "This reviewer has already reviewed this document"
                )
        
        return attrs
    
    def create(self, validated_data):
        # Set reviewed_at if status is not pending
        if validated_data.get('status') != 'pending':
            validated_data['reviewed_at'] = timezone.now()
        
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        # Update reviewed_at if status changed
        if 'status' in validated_data and validated_data['status'] != instance.status:
            validated_data['reviewed_at'] = timezone.now()
        
        return super().update(instance, validated_data)
    
    class Meta:
        model = CommitteeDocumentReview
        exclude = ['created_at', 'updated_at', 'is_published']


class CommitteeDocumentReviewReadSerializer(CommitteeDocumentReviewWriteSerializer):
    """
    Serializer for reading document reviews
    """
    
    document = FieldsRelatedField(fields=['id', 'title', 'version'])
    reviewer = FieldsRelatedField(fields=['id', 'first_name', 'last_name', 'email'])
    status = serializers.CharField(source='get_status_display')
    
    class Meta:
        model = CommitteeDocumentReview
        fields = "__all__"


class CommitteeDocumentVersionSerializer(serializers.Serializer):
    """
    Serializer for creating a new version
    """
    
    attachment = serializers.FileField(required=False)
    link = serializers.URLField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)
    create_as_current = serializers.BooleanField(default=True)
    
    def validate(self, attrs):
        if not attrs.get('attachment') and not attrs.get('link'):
            raise serializers.ValidationError(
                "Either attachment or link must be provided for new version"
            )
        return attrs


class CommitteeDocumentBulkUploadSerializer(serializers.Serializer):
    """
    Serializer for bulk uploading documents
    """
    
    files = serializers.ListField(
        child=serializers.FileField(),
        write_only=True
    )
    committee_id = serializers.UUIDField(required=True)
    meeting_id = serializers.UUIDField(required=False, allow_null=True)
    document_type = serializers.ChoiceField(
        choices=CommitteeDocument.DocumentType.choices,
        default=CommitteeDocument.DocumentType.OTHER
    )
    default_status = serializers.ChoiceField(
        choices=CommitteeDocument.Status.choices,
        default=CommitteeDocument.Status.DRAFT
    )
    notes = serializers.CharField(required=False, allow_blank=True)


class CommitteeDocumentPromoteSerializer(serializers.Serializer):
    """
    Serializer for promoting document status
    """
    
    new_status = serializers.ChoiceField(
        choices=CommitteeDocument.Status.choices
    )
    review_notes = serializers.CharField(required=False, allow_blank=True)
    approved_date = serializers.DateField(required=False)
    expiry_date = serializers.DateField(required=False)