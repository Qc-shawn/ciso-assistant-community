import uuid
import os
from django.db import transaction
from django.http import HttpResponse
from rest_framework import serializers
from django.utils import timezone
from core.models import DocumentCentre, Perimeter, Folder
from iam.models import User
from core.serializers import BaseModelSerializer, FieldsRelatedField, CustomDateField, PathField
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q, Count
from django.utils import timezone
from core.views import BaseModelViewSet
from .models import (
    Committee, CommitteeMember, CommitteeMeeting, 
    CommitteeMeetingAttendance, CommitteeDecision, CommitteeGRCLink, CommitteeDocument, CommitteeDocumentReview
)
from .serializers import (
    CommitteeWriteSerializer, CommitteeReadSerializer,
    CommitteeMemberWriteSerializer, CommitteeMemberReadSerializer,
    CommitteeMeetingWriteSerializer, CommitteeMeetingReadSerializer,
    CommitteeMeetingAttendanceWriteSerializer, CommitteeMeetingAttendanceReadSerializer,
    CommitteeDecisionWriteSerializer, CommitteeDecisionReadSerializer,
    CommitteeGRCLinkWriteSerializer, CommitteeGRCLinkReadSerializer,
    CommitteeDocumentWriteSerializer, CommitteeDocumentReadSerializer,
    CommitteeDocumentReviewWriteSerializer, CommitteeDocumentReviewReadSerializer,
    CommitteeDocumentVersionSerializer, CommitteeDocumentBulkUploadSerializer,
    CommitteeDocumentPromoteSerializer
)
from .filters import CommitteeFilter, CommitteeMemberFilter, CommitteeMeetingFilter, CommitteeDocumentFilter, CommitteeDocumentReviewFilter
from rest_framework import filters, generics, permissions, status, viewsets
from core.permissions import RBACPermissions


class CommitteeViewSet(BaseModelViewSet):
    """
    API endpoint for Committee management
    """
    
    model = Committee
    filterset_class = CommitteeFilter
    search_fields = ['name_en', 'name_ar', 'purpose']

    def get_serializer_class(self, action=None):
        if action is None:
            action = self.action
        
        if action in ['retrieve', 'list']:
            return CommitteeReadSerializer
        return CommitteeWriteSerializer
    
    def get_queryset(self):
        queryset = Committee.objects.all()
        
        if self.action in ['retrieve', 'list']:
            queryset = queryset.prefetch_related(
                'members', 'meetings'
                # , 'linked_documents'
            ).select_related(
                'folder', 'perimeter', 'default_secretary', 
                'decision_authority', 'agenda_template'
            )
        
        return queryset
    
    @action(detail=False, methods=['get'])
    def committee_types(self, request):
        """Get committee type choices"""
        return Response(dict(Committee.CommitteeType.choices))
    
    @action(detail=False, methods=['get'])
    def status_choices(self, request):
        """Get status choices"""
        return Response(dict(Committee.Status.choices))
    
    @action(detail=True, methods=['get'])
    def dashboard(self, request, pk):
        """Get committee dashboard data"""
        committee = self.get_object()
        
        data = {
            'committee': {
                'id': str(committee.id),
                'name': committee.name_en,
                'type': committee.get_committee_type_display(),
                'status': committee.get_status_display(),
                'members_count': committee.current_members_count,
                'required_quorum': committee.required_quorum,
            },
            'members': CommitteeMemberReadSerializer(
                committee.members.filter(membership_status='active'),
                many=True
            ).data,
            'upcoming_meetings': CommitteeMeetingReadSerializer(
                committee.meetings.filter(
                    status='scheduled',
                    start_datetime__gte=timezone.now()
                ).order_by('start_datetime')[:5],
                many=True
            ).data,
            'recent_decisions': CommitteeDecisionReadSerializer(
                committee.meetings.all().order_by('-created_at')[:5],
                many=True
            ).data,
            'statistics': {
                'total_meetings': committee.meetings.count(),
                'completed_meetings': committee.meetings.filter(status='completed').count(),
                'total_decisions': CommitteeDecision.objects.filter(meeting__committee=committee).count(),
                'grc_links': committee.grc_links.count(),
            }
        }
        
        return Response(data)


class CommitteeMemberViewSet(BaseModelViewSet):
    """
    API endpoint for Committee Members
    """
    
    model = CommitteeMember
    filterset_class = CommitteeMemberFilter
    search_fields = ['user__first_name', 'user__last_name', 'department']
    
    def get_serializer_class(self, action=None):
        if action is None:
            action = self.action
        
        if action in ['retrieve', 'list']:
            return CommitteeMemberReadSerializer
        return CommitteeMemberWriteSerializer
    
    def get_queryset(self):
        queryset = CommitteeMember.objects.all()
        
        if self.action in ['retrieve', 'list']:
            queryset = queryset.select_related(
                'committee', 'user', 'alternate_member'
            )
        
        return queryset
    
    @action(detail=False, methods=['get'])
    def role_choices(self, request):
        """Get role choices"""
        return Response(dict(CommitteeMember.Role.choices))


class CommitteeMeetingViewSet(BaseModelViewSet):
    """
    API endpoint for Committee Meetings
    """
    
    model = CommitteeMeeting
    filterset_class = CommitteeMeetingFilter
    search_fields = ['title', 'agenda']
    
    def get_serializer_class(self, action=None):
        if action is None:
            action = self.action
        
        if action in ['retrieve', 'list']:
            return CommitteeMeetingReadSerializer
        return CommitteeMeetingWriteSerializer
    
    def get_queryset(self):
        queryset = CommitteeMeeting.objects.all()
        
        if self.action in ['retrieve', 'list']:
            queryset = queryset.select_related(
                'committee', 'secretary', 'agenda_document', 'minutes_document'
            ).prefetch_related('attendance', 'decisions')
        
        return queryset
    
    @action(detail=True, methods=['post'])
    def complete(self, request, pk):
        """Mark meeting as completed"""
        meeting = self.get_object()
        
        meeting.status = CommitteeMeeting.Status.COMPLETED
        meeting.save()
        
        return Response({
            'detail': 'Meeting marked as completed',
            'meeting': CommitteeMeetingReadSerializer(meeting).data
        })
    
    @action(detail=True, methods=['post'])
    def record_attendance(self, request, pk):
        """Record attendance for meeting"""
        meeting = self.get_object()
        member_ids = request.data.get('member_ids', [])
        
        # Clear existing attendance
        meeting.attendance.all().delete()
        
        # Create attendance records
        for member_id in member_ids:
            try:
                member = CommitteeMember.objects.get(id=member_id)
                CommitteeMeetingAttendance.objects.create(
                    meeting=meeting,
                    member=member,
                    status='attended'
                )
            except CommitteeMember.DoesNotExist:
                pass
        
        # Update attendees count
        meeting.attendees_count = len(member_ids)
        meeting.save()
        
        return Response({
            'detail': f'Attendance recorded for {len(member_ids)} members',
            'attendees_count': meeting.attendees_count
        })


class CommitteeDecisionViewSet(BaseModelViewSet):
    """
    API endpoint for Committee Decisions
    """
    
    model = CommitteeDecision
    search_fields = ['title', 'description', 'comments']
    
    def get_serializer_class(self, action=None):
        if action is None:
            action = self.action
        
        if action in ['retrieve', 'list']:
            return CommitteeDecisionReadSerializer
        return CommitteeDecisionWriteSerializer
    
    def get_queryset(self):
        queryset = CommitteeDecision.objects.all()
        
        if self.action in ['retrieve', 'list']:
            queryset = queryset.select_related(
                'meeting', 'meeting__committee', 'supporting_document'
            )
        
        return queryset


class CommitteeGRCLinkViewSet(BaseModelViewSet):
    """
    API endpoint for GRC Links
    """
    
    model = CommitteeGRCLink
    search_fields = ['reason']
    
    def get_serializer_class(self, action=None):
        if action is None:
            action = self.action
        
        if action in ['retrieve', 'list']:
            return CommitteeGRCLinkReadSerializer
        return CommitteeGRCLinkWriteSerializer
    
    def get_queryset(self):
        queryset = CommitteeGRCLink.objects.all()
        
        if self.action in ['retrieve', 'list']:
            queryset = queryset.select_related('committee', 'linked_by')
        
        return queryset
    
    def perform_create(self, serializer):
        serializer.save(linked_by=self.request.user)



class CommitteeDocumentViewSet(BaseModelViewSet):
    """
    API endpoint for Committee Documents
    """
    
    model = CommitteeDocument
    filterset_class = CommitteeDocumentFilter
    search_fields = ['title', 'description', 'notes', 'file_name']
    permission_classes = [RBACPermissions]
    
    def get_serializer_class(self, action=None):
        if action is None:
            action = self.action
        
        if action in ['retrieve', 'list']:
            return CommitteeDocumentReadSerializer
        elif action in ['create', 'update', 'partial_update']:
            return CommitteeDocumentWriteSerializer
        elif action == 'create_version':
            return CommitteeDocumentVersionSerializer
        elif action == 'bulk_upload':
            return CommitteeDocumentBulkUploadSerializer
        elif action == 'promote':
            return CommitteeDocumentPromoteSerializer
        
        return super().get_serializer_class(action)
    
    def get_queryset(self):
        queryset = CommitteeDocument.objects.all()
        
        if self.action in ['retrieve', 'list']:
            queryset = queryset.select_related(
                'committee', 'meeting', 'folder', 'created_by', 
                'last_modified_by', 'approved_by', 'previous_version'
            ).prefetch_related('reviews', 'next_versions')
        
        return queryset
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, last_modified_by=self.request.user)
    
    def perform_update(self, serializer):
        serializer.save(last_modified_by=self.request.user)
    
    @action(detail=False, methods=['get'])
    def document_types(self, request):
        """Get document type choices"""
        return Response(dict(CommitteeDocument.DocumentType.choices))
    
    @action(detail=False, methods=['get'])
    def status_choices(self, request):
        """Get status choices"""
        return Response(dict(CommitteeDocument.Status.choices))
    
    @action(detail=True, methods=['post'])
    def create_version(self, request, pk):
        """Create a new version of this document"""
        document = self.get_object()
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            # Create new version
            new_version = document.create_new_version(user=request.user)
            
            # Update with new data
            if 'attachment' in serializer.validated_data:
                new_version.attachment = serializer.validated_data['attachment']
            if 'link' in serializer.validated_data:
                new_version.link = serializer.validated_data['link']
            if 'notes' in serializer.validated_data:
                new_version.notes = serializer.validated_data['notes']
            
            new_version.last_modified_by = request.user
            new_version.save()
            
            # Set as current if requested
            if serializer.validated_data.get('create_as_current', True):
                new_version.is_current = True
                new_version.save()
            
            response_serializer = CommitteeDocumentReadSerializer(
                new_version,
                context=self.get_serializer_context()
            )
            
            return Response(
                {
                    'detail': 'New version created successfully',
                    'document': response_serializer.data
                },
                status=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            return Response(
                {'detail': f'Error creating version: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def promote(self, request, pk):
        """Promote document status (e.g., from DRAFT to FINAL)"""
        document = self.get_object()
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        new_status = serializer.validated_data['new_status']
        old_status = document.status
        
        # Update document
        document.status = new_status
        
        if 'approved_date' in serializer.validated_data:
            document.approved_date = serializer.validated_data['approved_date']
        elif new_status == CommitteeDocument.Status.APPROVED:
            document.approved_date = timezone.now().date()
            document.approved_by = request.user
        
        if 'expiry_date' in serializer.validated_data:
            document.expiry_date = serializer.validated_data['expiry_date']
        
        if 'review_notes' in serializer.validated_data:
            document.notes = (document.notes or '') + f"\n\nStatus changed from {old_status} to {new_status}: {serializer.validated_data['review_notes']}"
        
        document.last_modified_by = request.user
        document.save()
        
        response_serializer = CommitteeDocumentReadSerializer(
            document,
            context=self.get_serializer_context()
        )
        
        return Response(
            {
                'detail': f'Document status updated to {new_status}',
                'document': response_serializer.data
            },
            status=status.HTTP_200_OK
        )
    
    @action(detail=True, methods=['get'])
    def download(self, request, pk):
        """Download document attachment"""
        document = self.get_object()
        
        if not document.attachment or not document.is_attachment_valid:
            return Response(
                {'detail': 'No valid attachment found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            file_path = document.attachment.path
            if os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    response = HttpResponse(
                        f.read(),
                        content_type=document.mime_type or 'application/octet-stream'
                    )
                    response['Content-Disposition'] = f'attachment; filename="{document.file_name or document.title}"'
                    response['Content-Length'] = document.file_size
                    return response
            else:
                return Response(
                    {'detail': 'File not found on server'},
                    status=status.HTTP_404_NOT_FOUND
                )
        except Exception as e:
            return Response(
                {'detail': f'Error downloading file: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def bulk_upload(self, request):
        """Bulk upload multiple documents for a committee"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            committee = Committee.objects.get(id=serializer.validated_data['committee_id'])
        except Committee.DoesNotExist:
            return Response(
                {'detail': 'Committee not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        meeting = None
        if serializer.validated_data.get('meeting_id'):
            try:
                meeting = CommitteeMeeting.objects.get(id=serializer.validated_data['meeting_id'])
            except CommitteeMeeting.DoesNotExist:
                return Response(
                    {'detail': 'Meeting not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        
        files = serializer.validated_data['files']
        document_type = serializer.validated_data.get('document_type', CommitteeDocument.DocumentType.OTHER)
        default_status = serializer.validated_data.get('default_status', CommitteeDocument.Status.DRAFT)
        notes = serializer.validated_data.get('notes', '')
        
        created_documents = []
        errors = []
        
        for file in files:
            try:
                # Use filename as title (without extension)
                title = os.path.splitext(file.name)[0]
                
                document = CommitteeDocument.objects.create(
                    title=title[:500],
                    committee=committee,
                    meeting=meeting,
                    document_type=document_type,
                    status=default_status,
                    created_by=request.user,
                    last_modified_by=request.user,
                    folder=committee.folder,
                    notes=notes,
                    attachment=file
                )
                
                created_documents.append({
                    'id': str(document.id),
                    'title': document.title,
                    'file_name': document.file_name
                })
                
            except Exception as e:
                errors.append({
                    'file': file.name,
                    'error': str(e)
                })
        
        response_data = {
            'detail': f'Successfully uploaded {len(created_documents)} files',
            'created_count': len(created_documents),
            'created_documents': created_documents,
        }
        
        if errors:
            response_data['errors'] = errors
        
        status_code = status.HTTP_201_CREATED if created_documents else status.HTTP_400_BAD_REQUEST
        
        return Response(response_data, status=status_code)
    
    @action(detail=False, methods=['get'])
    def by_committee(self, request):
        """Get all documents for a specific committee"""
        committee_id = request.query_params.get('committee_id')
        
        if not committee_id:
            return Response(
                {'detail': 'committee_id parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            committee = Committee.objects.get(id=committee_id)
        except Committee.DoesNotExist:
            return Response(
                {'detail': 'Committee not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        queryset = self.get_queryset().filter(committee=committee)
        queryset = self.filter_queryset(queryset)
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = CommitteeDocumentReadSerializer(
                page,
                many=True,
                context=self.get_serializer_context()
            )
            return self.get_paginated_response(serializer.data)
        
        serializer = CommitteeDocumentReadSerializer(
            queryset,
            many=True,
            context=self.get_serializer_context()
        )
        
        return Response({
            'committee': {
                'id': str(committee.id),
                'name': committee.name_en,
                'type': committee.get_committee_type_display()
            },
            'documents': serializer.data,
            'count': len(serializer.data)
        })
    
    @action(detail=False, methods=['get'])
    def by_meeting(self, request):
        """Get all documents for a specific meeting"""
        meeting_id = request.query_params.get('meeting_id')
        
        if not meeting_id:
            return Response(
                {'detail': 'meeting_id parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            meeting = CommitteeMeeting.objects.get(id=meeting_id)
        except CommitteeMeeting.DoesNotExist:
            return Response(
                {'detail': 'Meeting not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        queryset = self.get_queryset().filter(meeting=meeting)
        queryset = self.filter_queryset(queryset)
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = CommitteeDocumentReadSerializer(
                page,
                many=True,
                context=self.get_serializer_context()
            )
            return self.get_paginated_response(serializer.data)
        
        serializer = CommitteeDocumentReadSerializer(
            queryset,
            many=True,
            context=self.get_serializer_context()
        )
        
        return Response({
            'meeting': {
                'id': str(meeting.id),
                'title': meeting.title,
                'date': meeting.start_datetime
            },
            'documents': serializer.data,
            'count': len(serializer.data)
        })


class CommitteeDocumentReviewViewSet(BaseModelViewSet):
    """
    API endpoint for Document Reviews
    """
    
    model = CommitteeDocumentReview
    filterset_class = CommitteeDocumentReviewFilter
    search_fields = ['comments']
    permission_classes = [RBACPermissions]
    
    def get_serializer_class(self, action=None):
        if action is None:
            action = self.action
        
        if action in ['retrieve', 'list']:
            return CommitteeDocumentReviewReadSerializer
        return CommitteeDocumentReviewWriteSerializer
    
    def get_queryset(self):
        queryset = CommitteeDocumentReview.objects.all()
        
        if self.action in ['retrieve', 'list']:
            queryset = queryset.select_related('document', 'reviewer')
        
        return queryset