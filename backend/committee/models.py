import os
import re
import uuid
import hashlib
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from core.models import AbstractBaseModel, FolderMixin
from django.contrib.postgres.fields import ArrayField
from iam.models import User
from core.models import DocumentCentre, Perimeter
from django.utils.translation import gettext_lazy as _

class Committee(AbstractBaseModel, FolderMixin):
    """
    Core Committee model
    """
    
    class CommitteeType(models.TextChoices):
        REGULATOR = "regulator", "Regulator Committee"
        OPERATION = "operation", "Operation Committee"
        EXECUTIVE = "executive", "Executive Committee"
        SUB_COMMITTEE = "sub_committee", "Sub-Committee"
        PROJECT = "project", "Project Committee"
        AUDIT_RISK = "audit_risk", "Audit / Risk Committee"
    
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        SUSPENDED = "suspended", "Suspended"
        CLOSED = "closed", "Closed"
    
    class DurationType(models.TextChoices):
        PERMANENT = "permanent", "Permanent"
        TEMPORARY = "temporary", "Temporary"
    
    class VotingRule(models.TextChoices):
        SIMPLE_MAJORITY = "simple_majority", "Simple Majority"
        TWO_THIRDS = "two_thirds", "Two-thirds Majority"
        UNANIMOUS = "unanimous", "Unanimous"
    
    class MeetingFrequency(models.TextChoices):
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"
        AD_HOC = "ad_hoc", "Ad hoc"
    
    class MeetingMode(models.TextChoices):
        IN_PERSON = "in_person", "In-person"
        VIRTUAL = "virtual", "Virtual"
        HYBRID = "hybrid", "Hybrid"
    
    # Basic Information
    name_en = models.CharField(max_length=255, verbose_name="Name (English)")
    name_ar = models.CharField(max_length=255, blank=True, null=True, verbose_name="Name (Arabic)")
    committee_type = models.CharField(
        max_length=50,
        choices=CommitteeType.choices,
        verbose_name="Committee Type"
    )
    purpose = models.TextField(verbose_name="Purpose / Description")
    scope_of_authority = models.TextField(verbose_name="Scope of Authority")
    
    # Establishment & Status
    establishment_date = models.DateField(verbose_name="Establishment Date")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        verbose_name="Status"
    )
    
    # Duration
    duration_type = models.CharField(
        max_length=20,
        choices=DurationType.choices,
        default=DurationType.PERMANENT,
        verbose_name="Duration Type"
    )
    end_date = models.DateField(null=True, blank=True, verbose_name="End Date")
    closure_reason = models.TextField(null=True, blank=True, verbose_name="Closure Reason")
    
    # Quorum & Voting
    quorum_value = models.PositiveIntegerField(
        default=50,
        help_text="Percentage required for quorum",
        verbose_name="Quorum Requirement (%)"
    )
    voting_rule = models.CharField(
        max_length=20,
        choices=VotingRule.choices,
        default=VotingRule.SIMPLE_MAJORITY,
        verbose_name="Voting Rule"
    )
    
    # Meeting Configuration
    meeting_frequency = models.CharField(
        max_length=20,
        choices=MeetingFrequency.choices,
        default=MeetingFrequency.MONTHLY,
        verbose_name="Meeting Frequency"
    )
    default_meeting_mode = models.CharField(
        max_length=20,
        choices=MeetingMode.choices,
        default=MeetingMode.HYBRID,
        verbose_name="Default Meeting Mode"
    )
    default_location = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        verbose_name="Default Meeting Location"
    )
    virtual_meeting_link = models.URLField(
        null=True,
        blank=True,
        verbose_name="Virtual Meeting Link"
    )
    
    # Default Secretary
    default_secretary = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='default_secretary_committees',
        verbose_name="Default Secretary"
    )
    
    # Agenda Template (Document Centre integration)
    agenda_template = models.ForeignKey(
        DocumentCentre,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='committee_agenda_templates',
        verbose_name="Agenda Template"
    )
    
    # Minutes Required
    minutes_required = models.BooleanField(default=True, verbose_name="Minutes Required")
    
    # Decision Authority
    decision_authority = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='decision_authority_committees',
        verbose_name="Decision Authority"
    )
    
    # GRC Integration - Linked Documents (Multiple policies)
    # linked_documents = models.ManyToManyField(
    #     'core.DocumentCentre',
    #     blank=True,
    #     related_name='afaque_committees',
    #     verbose_name="Linked Documents"
    # )
    
    # Folder/Perimeter integration
    perimeter = models.ForeignKey(
        Perimeter,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="Perimeter",
        related_name="committees"
    )
    
    fields_to_check = ["name_en", "committee_type"]
    
    class Meta:
        app_label = "committee"
        verbose_name = "Committee"
        verbose_name_plural = "Committees"
        ordering = ['-establishment_date']
        permissions = [
            ("manage_committee_members", "Can manage committee members"),
            ("schedule_committee_meeting", "Can schedule committee meetings"),
            ("approve_committee_minutes", "Can approve committee minutes"),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['committee_type']),
        ]
    
    def __str__(self):
        return self.name_en
    
    def save(self, *args, **kwargs):
        if not self.folder and self.perimeter:
            self.folder = self.perimeter.folder
        super().save(*args, **kwargs)
    
    @property
    def current_members_count(self):
        return self.members.filter(membership_status='active').count()
    
    @property
    def required_quorum(self):
        total_members = self.current_members_count
        return int((self.quorum_value / 100) * total_members) if total_members else 0


class CommitteeMember(AbstractBaseModel):
    """
    Committee members
    """
    
    class Role(models.TextChoices):
        CHAIRPERSON = "chairperson", "Chairperson"
        VICE_CHAIR = "vice_chair", "Vice Chair"
        SECRETARY = "secretary", "Secretary"
        MEMBER = "member", "Member"
        ADVISOR = "advisor", "Advisor"
    
    class MembershipStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
    
    committee = models.ForeignKey(
        Committee,
        on_delete=models.CASCADE,
        related_name="members",
        verbose_name="Committee"
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="committee_memberships",
        verbose_name="User"
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MEMBER,
        verbose_name="Role"
    )
    department = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Department"
    )
    voting_rights = models.BooleanField(default=True, verbose_name="Voting Rights")
    joining_date = models.DateField(verbose_name="Joining Date")
    membership_status = models.CharField(
        max_length=20,
        choices=MembershipStatus.choices,
        default=MembershipStatus.ACTIVE,
        verbose_name="Status"
    )
    alternate_member = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primary_member",
        verbose_name="Alternate Member"
    )
    
    fields_to_check = ["committee", "user"]
    
    class Meta:
        app_label = "committee"
        verbose_name = "Committee Member"
        verbose_name_plural = "Committee Members"
        unique_together = [['committee', 'user']]
        ordering = ['committee', 'role', 'user__first_name']
    
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.get_role_display()}"


class CommitteeMeeting(AbstractBaseModel):
    """
    Committee meetings
    """
    
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
    
    class MeetingMode(models.TextChoices):
        IN_PERSON = "in_person", "In-person"
        VIRTUAL = "virtual", "Virtual"
        HYBRID = "hybrid", "Hybrid"
    
    committee = models.ForeignKey(
        Committee,
        on_delete=models.CASCADE,
        related_name="meetings",
        verbose_name="Committee"
    )
    title = models.CharField(max_length=500, verbose_name="Meeting Title")
    
    # Schedule
    start_datetime = models.DateTimeField(verbose_name="Start Date & Time")
    end_datetime = models.DateTimeField(verbose_name="End Date & Time")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
        verbose_name="Status"
    )
    
    # Location
    mode = models.CharField(
        max_length=20,
        choices=MeetingMode.choices,
        default=MeetingMode.HYBRID,
        verbose_name="Mode"
    )
    location = models.CharField(max_length=500, null=True, blank=True)
    virtual_link = models.URLField(null=True, blank=True)
    
    # Agenda & Minutes
    agenda = models.TextField(verbose_name="Agenda")
    agenda_document = models.ForeignKey(
        DocumentCentre,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='meeting_agendas',
        verbose_name="Agenda Document"
    )
    minutes = models.TextField(null=True, blank=True, verbose_name="Minutes")
    minutes_document = models.ForeignKey(
        DocumentCentre,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='meeting_minutes',
        verbose_name="Minutes Document"
    )
    
    # Secretary
    secretary = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='secretary_meetings',
        verbose_name="Secretary"
    )
    
    # Quorum
    quorum_achieved = models.BooleanField(default=False)
    attendees_count = models.PositiveIntegerField(default=0)
    
    fields_to_check = ["committee", "title"]
    
    class Meta:
        app_label = "committee"
        verbose_name = "Committee Meeting"
        verbose_name_plural = "Committee Meetings"
        ordering = ['-start_datetime']
        indexes = [
            models.Index(fields=['committee', 'status']),
            models.Index(fields=['start_datetime']),
        ]
    
    def __str__(self):
        return f"{self.committee.name_en} - {self.title} ({self.start_datetime.date()})"


class CommitteeMeetingAttendance(AbstractBaseModel):
    """
    Meeting attendance
    """
    
    class AttendanceStatus(models.TextChoices):
        ATTENDED = "attended", "Attended"
        ABSENT = "absent", "Absent"
        EXCUSED = "excused", "Excused"
    
    meeting = models.ForeignKey(
        CommitteeMeeting,
        on_delete=models.CASCADE,
        related_name="attendance"
    )
    member = models.ForeignKey(
        CommitteeMember,
        on_delete=models.CASCADE,
        related_name="meeting_attendance"
    )
    status = models.CharField(
        max_length=20,
        choices=AttendanceStatus.choices,
        default=AttendanceStatus.ATTENDED
    )
    represented_by = models.ForeignKey(
        CommitteeMember,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="represented_attendance"
    )
    
    class Meta:
        app_label = "committee"
        verbose_name = "Meeting Attendance"
        verbose_name_plural = "Meeting Attendances"
        unique_together = [['meeting', 'member']]


class CommitteeDecision(AbstractBaseModel):
    """
    Committee decisions
    """
    
    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        DEFERRED = "deferred", "Deferred"
    
    meeting = models.ForeignKey(
        CommitteeMeeting,
        on_delete=models.CASCADE,
        related_name="decisions",
        verbose_name="Meeting"
    )
    title = models.CharField(max_length=500, verbose_name="Decision Title")
    description = models.TextField(verbose_name="Decision Description")
    
    # Voting results
    votes_for = models.PositiveIntegerField(default=0)
    votes_against = models.PositiveIntegerField(default=0)
    votes_abstain = models.PositiveIntegerField(default=0)
    
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.APPROVED
    )
    
    # Supporting documents
    supporting_document = models.ForeignKey(
        DocumentCentre,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='committee_decisions',
        verbose_name="Supporting Document"
    )
    
    # Comments
    comments = models.TextField(null=True, blank=True, verbose_name="Comments")
    
    # Effective date
    effective_date = models.DateField(null=True, blank=True)
    
    fields_to_check = ["meeting", "title"]
    
    class Meta:
        app_label = "committee"
        verbose_name = "Committee Decision"
        verbose_name_plural = "Committee Decisions"
        ordering = ['-created_at']


class CommitteeGRCLink(AbstractBaseModel):
    """
    Link committee to GRC entities (Risks, Controls, Issues, Audits, Exceptions)
    """
    
    class EntityType(models.TextChoices):
        RISK = "risk", "Risk"
        CONTROL = "control", "Control"
        ISSUE = "issue", "Issue"
        AUDIT = "audit", "Audit"
        EXCEPTION = "exception", "Exception"
        PROJECT = "project", "Project"
    
    committee = models.ForeignKey(
        Committee,
        on_delete=models.CASCADE,
        related_name="grc_links"
    )
    entity_type = models.CharField(max_length=20, choices=EntityType.choices)
    entity_id = models.UUIDField(verbose_name="Linked Entity ID")
    
    # Link metadata
    linked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_grc_links"
    )
    reason = models.TextField(null=True, blank=True, verbose_name="Reason for linking")
    
    class Meta:
        app_label = "committee"
        verbose_name = "GRC Link"
        verbose_name_plural = "GRC Links"
        unique_together = [['committee', 'entity_type', 'entity_id']]
        indexes = [
            models.Index(fields=['entity_type', 'entity_id']),
        ]


def committee_document_upload_path(instance, filename):
    """
    Generate upload path for committee documents
    Format: committee_documents/<committee_id>/<document_type>/<filename>
    """
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    committee_id = instance.committee.id if instance.committee else 'no_committee'
    
    # Sanitize filename
    name, ext = os.path.splitext(filename)
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    
    return f"committee_documents/{committee_id}/{instance.document_type}/{timestamp}_{safe_name}{ext}"

class CommitteeDocument(AbstractBaseModel, FolderMixin):
    """
    Documents specifically for committees (Charters, Agendas, Minutes, Reports, etc.)
    """
    
    class DocumentType(models.TextChoices):
        CHARTER = "charter", _("Terms of Reference / Charter")
        AGENDA = "agenda", _("Agenda")
        MINUTES = "minutes", _("Minutes")
        REPORT = "report", _("Report")
        PRESENTATION = "presentation", _("Presentation")
        POLICY = "policy", _("Policy")
        DECISION = "decision", _("Decision Document")
        ATTACHMENT = "attachment", _("Attachment")
        OTHER = "other", _("Other")
    
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        FINAL = "final", _("Final")
        APPROVED = "approved", _("Approved")
        ARCHIVED = "archived", _("Archived")
        UNDER_REVIEW = "under_review", _("Under Review")
    
    # Core fields
    title = models.CharField(max_length=500, verbose_name=_("Title"))
    description = models.TextField(
        blank=True, 
        null=True,
        verbose_name=_("Description")
    )
    document_type = models.CharField(
        max_length=20,
        choices=DocumentType.choices,
        default=DocumentType.OTHER,
        verbose_name=_("Document Type")
    )
    
    # Status and versioning
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name=_("Status")
    )
    version = models.CharField(
        max_length=20,
        default="1.0",
        verbose_name=_("Version")
    )
    
    # Relationships
    committee = models.ForeignKey(
        Committee,
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name=_("Committee")
    )
    
    meeting = models.ForeignKey(
        CommitteeMeeting,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
        verbose_name=_("Related Meeting")
    )
    
    # File attachment
    attachment = models.FileField(
        upload_to=committee_document_upload_path,
        max_length=500,
        blank=True,
        null=True,
        verbose_name=_("Attachment")
    )
    
    # External link
    link = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name=_("External Link")
    )
    
    # Metadata
    file_size = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("File Size (bytes)")
    )
    file_name = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name=_("File Name")
    )
    mime_type = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name=_("MIME Type")
    )
    checksum = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        verbose_name=_("Checksum (SHA-256)")
    )
    page_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Page Count")
    )
    
    # Document tracking
    created_by = models.ForeignKey(
        'iam.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_committee_documents",
        verbose_name=_("Created By")
    )
    
    last_modified_by = models.ForeignKey(
        'iam.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="modified_committee_documents",
        verbose_name=_("Last Modified By")
    )
    
    # Review/approval tracking
    review_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Review Date")
    )
    approved_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Approved Date")
    )
    approved_by = models.ForeignKey(
        'iam.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_committee_documents",
        verbose_name=_("Approved By")
    )
    expiry_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Expiry Date")
    )
    
    # Version history - link to previous version
    previous_version = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="next_versions",
        verbose_name=_("Previous Version")
    )
    
    # Is this the current version?
    is_current = models.BooleanField(
        default=True,
        verbose_name=_("Is Current Version")
    )
    
    # Observations/notes
    notes = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Notes/Observations")
    )
    
    fields_to_check = ["title", "committee", "document_type"]
    
    class Meta:
        app_label = "committee"
        verbose_name = _("Committee Document")
        verbose_name_plural = _("Committee Documents")
        ordering = ['-created_at', '-version']
        indexes = [
            models.Index(fields=['committee', 'document_type']),
            models.Index(fields=['committee', 'status']),
            models.Index(fields=['committee', 'is_current']),
            models.Index(fields=['expiry_date']),
            models.Index(fields=['review_date']),
        ]
        permissions = [
            ("approve_committeedocument", "Can approve committee documents"),
            ("review_committeedocument", "Can review committee documents"),
            ("archive_committeedocument", "Can archive committee documents"),
        ]
    
    def __str__(self):
        return f"{self.committee.name_en} - {self.title} v{self.version} ({self.get_document_type_display()})"
    
    def save(self, *args, **kwargs):
        # Update file metadata if attachment is provided
        if self.attachment and not self.file_name:
            self.file_name = os.path.basename(self.attachment.name)
            self.file_size = self.attachment.size
            
            # Try to detect mime type
            try:
                import magic
                self.mime_type = magic.from_buffer(self.attachment.read(1024), mime=True)
                self.attachment.seek(0)
            except (ImportError, Exception):
                ext = os.path.splitext(self.attachment.name)[1].lower()
                mime_map = {
                    '.pdf': 'application/pdf',
                    '.doc': 'application/msword',
                    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    '.xls': 'application/vnd.ms-excel',
                    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    '.ppt': 'application/vnd.ms-powerpoint',
                    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                    '.txt': 'text/plain',
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.png': 'image/png',
                }
                self.mime_type = mime_map.get(ext, 'application/octet-stream')
            
            # Calculate checksum
            self.checksum = self._calculate_checksum()
        
        # Set folder from committee if not provided
        if not self.folder and self.committee:
            self.folder = self.committee.folder
        
        super().save(*args, **kwargs)
        
        # If this is set as current, ensure other versions are not current
        if self.is_current and self.committee:
            CommitteeDocument.objects.filter(
                committee=self.committee,
                document_type=self.document_type,
                is_current=True
            ).exclude(id=self.id).update(is_current=False)
    
    def _calculate_checksum(self):
        """Calculate SHA-256 checksum of attachment"""
        if not self.attachment:
            return None
        
        try:
            self.attachment.seek(0)
            sha256 = hashlib.sha256()
            for chunk in self.attachment.chunks():
                sha256.update(chunk)
            self.attachment.seek(0)
            return sha256.hexdigest()
        except Exception:
            return None
    
    @property
    def is_attachment_valid(self):
        """Check if attachment file still exists"""
        if not self.attachment:
            return False
        try:
            return self.attachment.storage.exists(self.attachment.name)
        except Exception:
            return False
    
    @property
    def formatted_file_size(self):
        """Return file size in human readable format"""
        if not self.file_size:
            return None
        
        size = self.file_size
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / 1024 / 1024:.1f} MB"
        else:
            return f"{size / 1024 / 1024 / 1024:.1f} GB"
    
    def create_new_version(self, user=None):
        """
        Create a new version of this document
        """
        # Mark current as not current
        self.is_current = False
        self.save()
        
        # Parse version
        try:
            major, minor = map(int, self.version.split('.'))
            new_version_str = f"{major}.{minor + 1}"
        except:
            new_version_str = "1.1"
        
        # Create new version
        new_document = CommitteeDocument.objects.create(
            title=self.title,
            description=self.description,
            document_type=self.document_type,
            status=CommitteeDocument.Status.DRAFT,
            version=new_version_str,
            committee=self.committee,
            meeting=self.meeting,
            created_by=user or self.created_by,
            folder=self.folder,
            previous_version=self,
            notes=self.notes,
        )
        
        return new_document


class CommitteeDocumentReview(AbstractBaseModel):
    """
    Track reviews of committee documents
    """
    
    class ReviewStatus(models.TextChoices):
        PENDING = "pending", _("Pending")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        CHANGES_REQUESTED = "changes_requested", _("Changes Requested")
    
    document = models.ForeignKey(
        CommitteeDocument,
        on_delete=models.CASCADE,
        related_name="reviews",
        verbose_name=_("Document")
    )
    
    reviewer = models.ForeignKey(
        'iam.User',
        on_delete=models.CASCADE,
        related_name="committee_document_reviews",
        verbose_name=_("Reviewer")
    )
    
    status = models.CharField(
        max_length=20,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
        verbose_name=_("Status")
    )
    
    comments = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Review Comments")
    )
    
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Reviewed At")
    )
    
    class Meta:
        app_label = "committee"
        verbose_name = _("Document Review")
        verbose_name_plural = _("Document Reviews")
        unique_together = [['document', 'reviewer']]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.document.title} - {self.reviewer.email} - {self.get_status_display()}"