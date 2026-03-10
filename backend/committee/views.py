import uuid
import os
from django.db import transaction
from django.db import models
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
        """Get comprehensive committee dashboard with all reporting data"""
        committee = self.get_object()
        
        # Basic committee info
        committee_data = CommitteeReadSerializer(committee).data
        
        # Members data
        active_members = committee.members.filter(membership_status='active').select_related('user')
        members_data = CommitteeMemberReadSerializer(active_members, many=True).data
        
        # Meetings data
        all_meetings = committee.meetings.all().order_by('-start_datetime')
        upcoming_meetings = all_meetings.filter(
            status='scheduled',
            start_datetime__gte=timezone.now()
        )[:5]
        past_meetings = all_meetings.filter(
            status='completed'
        )[:10]
        
        upcoming_meetings_data = CommitteeMeetingReadSerializer(upcoming_meetings, many=True).data
        past_meetings_data = CommitteeMeetingReadSerializer(past_meetings, many=True).data
        
        # Decisions data
        recent_decisions = CommitteeDecision.objects.filter(
            meeting__committee=committee
        ).select_related('meeting').order_by('-created_at')[:20]
        decisions_data = CommitteeDecisionReadSerializer(recent_decisions, many=True).data
        
        # Documents data
        documents = committee.documents.filter(is_current=True).order_by('-created_at')[:20]
        documents_data = CommitteeDocumentReadSerializer(documents, many=True).data
        
        # GRC Links data
        grc_links = committee.grc_links.all().select_related('linked_by')
        grc_links_data = CommitteeGRCLinkReadSerializer(grc_links, many=True).data
        
        # Statistics
        total_members = committee.members.count()
        active_members_count = active_members.count()
        total_meetings = all_meetings.count()
        completed_meetings = all_meetings.filter(status='completed').count()
        scheduled_meetings = all_meetings.filter(status='scheduled').count()
        total_decisions = CommitteeDecision.objects.filter(meeting__committee=committee).count()
        approved_decisions = CommitteeDecision.objects.filter(
            meeting__committee=committee, 
            status='approved'
        ).count()
        total_documents = committee.documents.count()
        current_documents = committee.documents.filter(is_current=True).count()
        total_grc_links = grc_links.count()
        
        # Attendance statistics
        attendance_stats = {}
        for meeting in all_meetings.filter(status='completed'):
            attendance_stats[str(meeting.id)] = {
                'meeting_title': meeting.title,
                'meeting_date': meeting.start_datetime,
                'attendees': meeting.attendees_count,
                'total_members': active_members_count,
                'attendance_rate': (meeting.attendees_count / active_members_count * 100) if active_members_count > 0 else 0
            }
        
        # Decision statistics by meeting
        decisions_by_meeting = []
        for meeting in all_meetings.filter(status='completed')[:10]:
            meeting_decisions = CommitteeDecision.objects.filter(meeting=meeting)
            decisions_by_meeting.append({
                'meeting_id': str(meeting.id),
                'meeting_title': meeting.title,
                'meeting_date': meeting.start_datetime,
                'total_decisions': meeting_decisions.count(),
                'approved': meeting_decisions.filter(status='approved').count(),
                'deferred': meeting_decisions.filter(status='deferred').count(),
                'rejected': meeting_decisions.filter(status='rejected').count(),
            })
        
        # Documents by type
        documents_by_type = {}
        for doc_type, label in CommitteeDocument.DocumentType.choices:
            count = committee.documents.filter(document_type=doc_type).count()
            if count > 0:
                documents_by_type[doc_type] = {
                    'label': label,
                    'count': count
                }
        
        # GRC Links by entity type
        grc_links_by_type = {}
        for entity_type, label in CommitteeGRCLink.EntityType.choices:
            count = committee.grc_links.filter(entity_type=entity_type).count()
            if count > 0:
                grc_links_by_type[entity_type] = {
                    'label': label,
                    'count': count
                }
        
        # Timeline/Activity feed
        activity_feed = []
        
        # Add recent meetings
        for meeting in all_meetings[:5]:
            activity_feed.append({
                'id': str(meeting.id),
                'type': 'meeting',
                'title': meeting.title,
                'date': meeting.start_datetime,
                'status': meeting.get_status_display(),
                'description': f"Meeting {'scheduled' if meeting.status == 'scheduled' else 'held'} on {meeting.start_datetime.strftime('%Y-%m-%d')}"
            })
        
        # Add recent decisions
        for decision in recent_decisions[:5]:
            activity_feed.append({
                'id': str(decision.id),
                'type': 'decision',
                'title': decision.title,
                'date': decision.created_at,
                'status': decision.get_status_display(),
                'description': f"Decision {decision.get_status_display()}: {decision.description[:100]}..."
            })
        
        # Add recent documents
        for doc in documents[:5]:
            activity_feed.append({
                'id': str(doc.id),
                'type': 'document',
                'title': doc.title,
                'date': doc.created_at,
                'status': doc.get_status_display(),
                'description': f"Document {doc.get_status_display()}: {doc.description[:100] if doc.description else ''}"
            })
        
        # Sort activity feed by date (newest first)
        activity_feed.sort(key=lambda x: x['date'], reverse=True)
        
        # Comprehensive dashboard response
        dashboard_data = {
            'committee': committee_data,
            'summary': {
                'total_members': total_members,
                'active_members': active_members_count,
                'total_meetings': total_meetings,
                'completed_meetings': completed_meetings,
                'scheduled_meetings': scheduled_meetings,
                'total_decisions': total_decisions,
                'approved_decisions': approved_decisions,
                'approval_rate': (approved_decisions / total_decisions * 100) if total_decisions > 0 else 0,
                'total_documents': total_documents,
                'current_documents': current_documents,
                'total_grc_links': total_grc_links,
            },
            'members': {
                'active': members_data,
                'by_role': self._get_members_by_role(committee),
                'by_department': self._get_members_by_department(committee),
            },
            'meetings': {
                'upcoming': upcoming_meetings_data,
                'recent': past_meetings_data,
                'attendance_stats': attendance_stats,
                'decisions_by_meeting': decisions_by_meeting,
            },
            'decisions': {
                'recent': decisions_data,
                'by_status': self._get_decisions_by_status(committee),
                'by_meeting': decisions_by_meeting,
            },
            'documents': {
                'recent': documents_data,
                'by_type': documents_by_type,
                'by_status': self._get_documents_by_status(committee),
            },
            'grc_links': {
                'all': grc_links_data,
                'by_type': grc_links_by_type,
            },
            'activity_feed': activity_feed[:20],  # Last 20 activities
            'performance_metrics': {
                'meeting_frequency_actual': self._get_actual_meeting_frequency(committee),
                'decision_effectiveness': self._get_decision_effectiveness(committee),
                'member_participation_rate': self._get_participation_rate(committee),
                'document_completion_rate': self._get_document_completion_rate(committee),
            }
        }
        
        return Response(dashboard_data)

    @action(detail=False, methods=['get'], url_path='all-committees-dashboard')
    def all_committees_dashboard(self, request):
        """
        Get comprehensive dashboard for ALL committees
        Provides aggregated statistics and cross-committee reporting
        """
        from django.db.models import Count, Avg, Sum, Q, F, OuterRef, Subquery
        from django.db.models.functions import TruncMonth
        from django.utils import timezone
        from .models import Committee, CommitteeMember, CommitteeMeeting, CommitteeDecision, CommitteeDocument, CommitteeGRCLink
        
        # Get all committees with optimizations
        committees = Committee.objects.all().select_related('folder')
        
        # Apply filters if any
        filtered_committees = self.filter_queryset(committees)
        
        # Get committee IDs for filtering related objects
        committee_ids = filtered_committees.values_list('id', flat=True)
        
        # ===== BASIC STATISTICS =====
        total_committees = filtered_committees.count()
        
        # Committees by type
        committees_by_type = []
        for committee_type, label in Committee.CommitteeType.choices:
            count = filtered_committees.filter(committee_type=committee_type).count()
            if count > 0:
                committees_by_type.append({
                    'type': committee_type,
                    'label': label,
                    'count': count,
                    'percentage': round((count / total_committees * 100), 1) if total_committees > 0 else 0
                })
        
        # Committees by status
        committees_by_status = []
        for status_code, label in Committee.Status.choices:
            count = filtered_committees.filter(status=status_code).count()
            if count > 0:
                committees_by_status.append({
                    'status': status_code,
                    'label': label,
                    'count': count,
                    'percentage': round((count / total_committees * 100), 1) if total_committees > 0 else 0
                })
        
        # Committees by duration type
        committees_by_duration = []
        for duration, label in Committee.DurationType.choices:
            count = filtered_committees.filter(duration_type=duration).count()
            if count > 0:
                committees_by_duration.append({
                    'duration': duration,
                    'label': label,
                    'count': count,
                    'percentage': round((count / total_committees * 100), 1) if total_committees > 0 else 0
                })
        
        # Committees by meeting frequency
        committees_by_frequency = []
        for freq, label in Committee.MeetingFrequency.choices:
            count = filtered_committees.filter(meeting_frequency=freq).count()
            if count > 0:
                committees_by_frequency.append({
                    'frequency': freq,
                    'label': label,
                    'count': count,
                    'percentage': round((count / total_committees * 100), 1) if total_committees > 0 else 0
                })
        
        # ===== MEMBER STATISTICS =====
        # Use the correct related name - check what it is in your model
        # In CommitteeMember model, the related name is likely 'members' (plural)
        all_members = CommitteeMember.objects.filter(
            committee_id__in=committee_ids
        ).select_related('user', 'committee')
        
        total_members = all_members.count()
        
        active_members = all_members.filter(
            membership_status='active'
        ).count()
        
        # Members by role across all committees
        members_by_role = list(
            all_members.values('role').annotate(
                count=Count('id')
            ).order_by('role')
        )
        
        # Add labels to roles
        for item in members_by_role:
            item['label'] = dict(CommitteeMember.Role.choices).get(item['role'], item['role'])
        
        # Members with voting rights
        voting_members = all_members.filter(
            voting_rights=True
        ).count()
        
        # Average members per committee
        avg_members_per_committee = round(total_members / total_committees, 1) if total_committees > 0 else 0
        
        # Top committees by member count - use Subquery to avoid annotation issues
        top_committees_by_members = []
        for committee in filtered_committees:
            member_count = committee.members.count()  # Using the related manager directly
            if member_count > 0:
                top_committees_by_members.append({
                    'id': str(committee.id),
                    'name_en': committee.name_en,
                    'member_count': member_count
                })
        
        # Sort and take top 5
        top_committees_by_members = sorted(
            top_committees_by_members, 
            key=lambda x: x['member_count'], 
            reverse=True
        )[:5]
        
        # ===== MEETING STATISTICS =====
        all_meetings = CommitteeMeeting.objects.filter(
            committee_id__in=committee_ids
        ).select_related('committee')
        
        total_meetings = all_meetings.count()
        
        # Meetings by status
        meetings_by_status = []
        for status_code, label in CommitteeMeeting.Status.choices:
            count = all_meetings.filter(status=status_code).count()
            if count > 0:
                meetings_by_status.append({
                    'status': status_code,
                    'label': label,
                    'count': count,
                    'percentage': round((count / total_meetings * 100), 1) if total_meetings > 0 else 0
                })
        
        # Meetings by mode
        meetings_by_mode = []
        for mode_code, label in CommitteeMeeting.MeetingMode.choices:
            count = all_meetings.filter(mode=mode_code).count()
            if count > 0:
                meetings_by_mode.append({
                    'mode': mode_code,
                    'label': label,
                    'count': count,
                    'percentage': round((count / total_meetings * 100), 1) if total_meetings > 0 else 0
                })
        
        # Upcoming meetings (next 30 days)
        upcoming_meetings = all_meetings.filter(
            status='scheduled',
            start_datetime__gte=timezone.now(),
            start_datetime__lte=timezone.now() + timezone.timedelta(days=30)
        ).order_by('start_datetime')[:20]
        
        upcoming_meetings_data = []
        for meeting in upcoming_meetings:
            upcoming_meetings_data.append({
                'id': str(meeting.id),
                'title': meeting.title,
                'committee_id': str(meeting.committee.id),
                'committee_name': meeting.committee.name_en,
                'start_datetime': meeting.start_datetime,
                'end_datetime': meeting.end_datetime,
                'mode': meeting.get_mode_display(),
                'location': meeting.location,
                'virtual_link': meeting.virtual_link,
            })
        
        # Overdue meetings (past scheduled but not completed)
        overdue_meetings = all_meetings.filter(
            status='scheduled',
            start_datetime__lt=timezone.now()
        )
        overdue_meetings_count = overdue_meetings.count()
        
        # Meeting attendance metrics
        completed_meetings = all_meetings.filter(status='completed')
        completed_meetings_count = completed_meetings.count()
        
        total_attendees = sum(m.attendees_count for m in completed_meetings)
        avg_attendance = round(total_attendees / completed_meetings_count, 1) if completed_meetings_count > 0 else 0
        
        # ===== DECISION STATISTICS =====
        all_decisions = CommitteeDecision.objects.filter(
            meeting__committee_id__in=committee_ids
        ).select_related('meeting', 'meeting__committee')
        
        total_decisions = all_decisions.count()
        
        # Decisions by status
        decisions_by_status = []
        for status_code, label in CommitteeDecision.Status.choices:
            count = all_decisions.filter(status=status_code).count()
            if count > 0:
                decisions_by_status.append({
                    'status': status_code,
                    'label': label,
                    'count': count,
                    'percentage': round((count / total_decisions * 100), 1) if total_decisions > 0 else 0
                })
        
        # Decisions over time (by month)
        decisions_by_month = list(
            all_decisions.annotate(
                month=TruncMonth('created_at')
            ).values('month').annotate(
                count=Count('id')
            ).order_by('month')
        )
        
        # Format dates for response
        for item in decisions_by_month:
            if item['month']:
                item['month'] = item['month'].strftime('%Y-%m')
        
        # Top committees by decisions
        committee_decision_counts = {}
        for decision in all_decisions:
            committee_id = str(decision.meeting.committee.id)
            committee_name = decision.meeting.committee.name_en
            if committee_id not in committee_decision_counts:
                committee_decision_counts[committee_id] = {
                    'id': committee_id,
                    'name_en': committee_name,
                    'decision_count': 0
                }
            committee_decision_counts[committee_id]['decision_count'] += 1
        
        top_committees_by_decisions = sorted(
            committee_decision_counts.values(),
            key=lambda x: x['decision_count'],
            reverse=True
        )[:5]
        
        # Voting statistics
        voting_stats = all_decisions.aggregate(
            avg_votes_for=Avg('votes_for'),
            avg_votes_against=Avg('votes_against'),
            avg_votes_abstain=Avg('votes_abstain'),
            total_votes_cast=Sum('votes_for') + Sum('votes_against') + Sum('votes_abstain')
        )
        
        # ===== DOCUMENT STATISTICS =====
        all_documents = CommitteeDocument.objects.filter(
            committee_id__in=committee_ids
        ).select_related('committee')
        
        total_documents = all_documents.count()
        current_documents = all_documents.filter(is_current=True).count()
        
        # Documents by type
        documents_by_type = []
        for doc_type, label in CommitteeDocument.DocumentType.choices:
            count = all_documents.filter(document_type=doc_type).count()
            if count > 0:
                documents_by_type.append({
                    'type': doc_type,
                    'label': label,
                    'count': count,
                    'percentage': round((count / total_documents * 100), 1) if total_documents > 0 else 0
                })
        
        # Documents by status
        documents_by_status = []
        for status_code, label in CommitteeDocument.Status.choices:
            count = all_documents.filter(status=status_code).count()
            if count > 0:
                documents_by_status.append({
                    'status': status_code,
                    'label': label,
                    'count': count,
                    'percentage': round((count / total_documents * 100), 1) if total_documents > 0 else 0
                })
        
        # Documents expiring soon (next 90 days)
        expiring_documents = all_documents.filter(
            expiry_date__isnull=False,
            expiry_date__gte=timezone.now().date(),
            expiry_date__lte=timezone.now().date() + timezone.timedelta(days=90)
        ).order_by('expiry_date')[:20]
        
        expiring_documents_data = []
        for doc in expiring_documents:
            expiring_documents_data.append({
                'id': str(doc.id),
                'title': doc.title,
                'committee_id': str(doc.committee.id),
                'committee_name': doc.committee.name_en,
                'document_type': doc.get_document_type_display(),
                'expiry_date': doc.expiry_date,
                'days_until_expiry': (doc.expiry_date - timezone.now().date()).days,
                'status': doc.get_status_display(),
            })
        
        # ===== GRC LINK STATISTICS =====
        all_grc_links = CommitteeGRCLink.objects.filter(
            committee_id__in=committee_ids
        ).select_related('committee', 'linked_by')
        
        total_grc_links = all_grc_links.count()
        
        # GRC links by entity type
        grc_links_by_type = []
        for entity_type, label in CommitteeGRCLink.EntityType.choices:
            count = all_grc_links.filter(entity_type=entity_type).count()
            if count > 0:
                grc_links_by_type.append({
                    'entity_type': entity_type,
                    'label': label,
                    'count': count,
                    'percentage': round((count / total_grc_links * 100), 1) if total_grc_links > 0 else 0
                })
        
        # Top committees by GRC links
        committee_grc_counts = {}
        for link in all_grc_links:
            committee_id = str(link.committee.id)
            committee_name = link.committee.name_en
            if committee_id not in committee_grc_counts:
                committee_grc_counts[committee_id] = {
                    'id': committee_id,
                    'name_en': committee_name,
                    'grc_count': 0
                }
            committee_grc_counts[committee_id]['grc_count'] += 1
        
        top_committees_by_grc = sorted(
            committee_grc_counts.values(),
            key=lambda x: x['grc_count'],
            reverse=True
        )[:5]
        
        # ===== ACTIVITY TIMELINE =====
        activity_feed = []
        
        # Add recent meetings
        recent_meetings = all_meetings.order_by('-created_at')[:10]
        for meeting in recent_meetings:
            activity_feed.append({
                'id': str(meeting.id),
                'committee_id': str(meeting.committee.id),
                'committee_name': meeting.committee.name_en,
                'type': 'meeting',
                'title': meeting.title,
                'date': meeting.created_at,
                'event_date': meeting.start_datetime,
                'status': meeting.get_status_display(),
                'description': f"Meeting {meeting.get_status_display()} for {meeting.committee.name_en}"
            })
        
        # Add recent decisions
        recent_decisions = all_decisions.order_by('-created_at')[:10]
        for decision in recent_decisions:
            activity_feed.append({
                'id': str(decision.id),
                'committee_id': str(decision.meeting.committee.id),
                'committee_name': decision.meeting.committee.name_en,
                'type': 'decision',
                'title': decision.title,
                'date': decision.created_at,
                'event_date': decision.created_at,
                'status': decision.get_status_display(),
                'description': f"Decision {decision.get_status_display()}: {decision.description[:100]}..."
            })
        
        # Add recent documents
        recent_documents = all_documents.order_by('-created_at')[:10]
        for doc in recent_documents:
            activity_feed.append({
                'id': str(doc.id),
                'committee_id': str(doc.committee.id),
                'committee_name': doc.committee.name_en,
                'type': 'document',
                'title': doc.title,
                'date': doc.created_at,
                'event_date': doc.created_at,
                'status': doc.get_status_display(),
                'description': f"Document {doc.get_status_display()}: {doc.title}"
            })
        
        # Sort activity feed by date
        activity_feed.sort(key=lambda x: x['date'], reverse=True)
        
        # ===== COMPLIANCE & GOVERNANCE METRICS =====
        
        # Committees with quorum requirements
        committees_with_quorum = filtered_committees.filter(quorum_value__gt=0).count()
        
        # Committees with minutes required
        committees_with_minutes = filtered_committees.filter(minutes_required=True).count()
        
        # Meeting completion rate
        meeting_completion_rate = round((completed_meetings_count / total_meetings * 100), 1) if total_meetings > 0 else 0
        
        # Decision approval rate
        approved_decisions = all_decisions.filter(status='approved').count()
        decision_approval_rate = round((approved_decisions / total_decisions * 100), 1) if total_decisions > 0 else 0
        
        # Document finalization rate
        final_documents = all_documents.filter(status='final').count()
        document_finalization_rate = round((final_documents / total_documents * 100), 1) if total_documents > 0 else 0
        
        # ===== RESPONSE =====
        response_data = {
            'generated_at': timezone.now().isoformat(),
            'filters_applied': dict(request.query_params),
            
            'summary': {
                'total_committees': total_committees,
                'total_members': total_members,
                'active_members': active_members,
                'voting_members': voting_members,
                'total_meetings': total_meetings,
                'upcoming_meetings': upcoming_meetings.count(),
                'overdue_meetings': overdue_meetings_count,
                'total_decisions': total_decisions,
                'total_documents': total_documents,
                'current_documents': current_documents,
                'total_grc_links': total_grc_links,
                'committees_with_quorum': committees_with_quorum,
                'committees_with_minutes': committees_with_minutes,
                'meeting_completion_rate': meeting_completion_rate,
                'decision_approval_rate': decision_approval_rate,
                'document_finalization_rate': document_finalization_rate,
                'avg_members_per_committee': avg_members_per_committee,
                'avg_attendance_per_meeting': avg_attendance,
            },
            
            'committees': {
                'by_type': committees_by_type,
                'by_status': committees_by_status,
                'by_duration': committees_by_duration,
                'by_frequency': committees_by_frequency,
                'top_by_members': top_committees_by_members,
                'top_by_decisions': top_committees_by_decisions,
                'top_by_grc': top_committees_by_grc,
            },
            
            'members': {
                'total': total_members,
                'active': active_members,
                'voting_members': voting_members,
                'avg_per_committee': avg_members_per_committee,
                'by_role': members_by_role,
            },
            
            'meetings': {
                'total': total_meetings,
                'completed': completed_meetings_count,
                'scheduled': all_meetings.filter(status='scheduled').count(),
                'cancelled': all_meetings.filter(status='cancelled').count(),
                'by_status': meetings_by_status,
                'by_mode': meetings_by_mode,
                'upcoming': upcoming_meetings_data,
                'overdue_count': overdue_meetings_count,
                'attendance': {
                    'total_attendees': total_attendees,
                    'avg_per_meeting': avg_attendance,
                    'attendance_rate': round((total_attendees / (completed_meetings_count * avg_members_per_committee)) * 100, 1) if completed_meetings_count > 0 and avg_members_per_committee > 0 else 0,
                },
            },
            
            'decisions': {
                'total': total_decisions,
                'by_status': decisions_by_status,
                'by_month': decisions_by_month,
                'voting_stats': {
                    'avg_votes_for': round(voting_stats['avg_votes_for'] or 0, 1),
                    'avg_votes_against': round(voting_stats['avg_votes_against'] or 0, 1),
                    'avg_votes_abstain': round(voting_stats['avg_votes_abstain'] or 0, 1),
                    'total_votes_cast': voting_stats['total_votes_cast'] or 0,
                },
            },
            
            'documents': {
                'total': total_documents,
                'current': current_documents,
                'by_type': documents_by_type,
                'by_status': documents_by_status,
                'expiring_soon': expiring_documents_data,
                'expiring_count': len(expiring_documents_data),
            },
            
            'grc_links': {
                'total': total_grc_links,
                'by_type': grc_links_by_type,
            },
            
            'activity_feed': activity_feed[:30],
            
            'governance_health': {
                'quorum_compliance': round((committees_with_quorum / total_committees * 100), 1) if total_committees > 0 else 0,
                'minutes_compliance': round((committees_with_minutes / total_committees * 100), 1) if total_committees > 0 else 0,
                'meeting_adherence': meeting_completion_rate,
                'decision_effectiveness': decision_approval_rate,
                'document_maturity': document_finalization_rate,
                'member_participation': round((active_members / total_members * 100), 1) if total_members > 0 else 0,
            },
        }
        
        return Response(response_data)

    def _get_members_by_role(self, committee):
        """Get member counts by role"""
        from django.db.models import Count
        return list(committee.members.values('role').annotate(
            count=Count('id')
        ).order_by('role'))

    def _get_members_by_department(self, committee):
        """Get member counts by department"""
        from django.db.models import Count
        return list(committee.members.values('department').annotate(
            count=Count('id')
        ).order_by('department'))

    def _get_decisions_by_status(self, committee):
        """Get decision counts by status"""
        from django.db.models import Count
        return list(CommitteeDecision.objects.filter(
            meeting__committee=committee
        ).values('status').annotate(
            count=Count('id')
        ).order_by('status'))

    def _get_documents_by_status(self, committee):
        """Get document counts by status"""
        from django.db.models import Count
        return list(committee.documents.values('status').annotate(
            count=Count('id')
        ).order_by('status'))

    def _get_actual_meeting_frequency(self, committee):
        """Calculate actual meeting frequency"""
        meetings = committee.meetings.filter(status='completed').order_by('start_datetime')
        if meetings.count() < 2:
            return None
        
        # Calculate average days between meetings
        dates = [m.start_datetime.date() for m in meetings]
        intervals = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
        avg_interval = sum(intervals) / len(intervals)
        
        return {
            'average_days_between': round(avg_interval, 1),
            'meetings_per_year': round(365 / avg_interval, 1) if avg_interval > 0 else 0,
            'total_meetings': meetings.count(),
            'period': f"{dates[0]} to {dates[-1]}"
        }

    def _get_decision_effectiveness(self, committee):
        """Calculate decision effectiveness metrics"""
        decisions = CommitteeDecision.objects.filter(meeting__committee=committee)
        total = decisions.count()
        
        if total == 0:
            return None
        
        return {
            'total_decisions': total,
            'approved': decisions.filter(status='approved').count(),
            'approval_rate': decisions.filter(status='approved').count() / total * 100,
            'deferred_rate': decisions.filter(status='deferred').count() / total * 100,
            'rejected_rate': decisions.filter(status='rejected').count() / total * 100,
            'avg_votes_for': decisions.aggregate(avg=models.Avg('votes_for'))['avg'],
            'avg_votes_against': decisions.aggregate(avg=models.Avg('votes_against'))['avg'],
        }

    def _get_participation_rate(self, committee):
        """Calculate member participation rate across meetings"""
        meetings = committee.meetings.filter(status='completed')
        if meetings.count() == 0:
            return None
        
        total_members = committee.members.filter(membership_status='active').count()
        if total_members == 0:
            return None
        
        total_attendances = sum(m.attendees_count for m in meetings)
        possible_attendances = meetings.count() * total_members
        
        return {
            'overall_rate': (total_attendances / possible_attendances * 100) if possible_attendances > 0 else 0,
            'average_per_meeting': total_attendances / meetings.count(),
            'total_meetings': meetings.count(),
            'total_members': total_members,
        }

    def _get_document_completion_rate(self, committee):
        """Calculate document completion metrics"""
        documents = committee.documents.all()
        total = documents.count()
        
        if total == 0:
            return None
        
        return {
            'total_documents': total,
            'current_versions': documents.filter(is_current=True).count(),
            'by_status': list(documents.values('status').annotate(
                count=Count('id')
            ).order_by('status')),
            'completion_rate': documents.filter(status='final').count() / total * 100,
        }


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