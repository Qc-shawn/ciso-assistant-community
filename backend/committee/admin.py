# from django.contrib import admin
# from .models import (
#     Committee, CommitteeMember, CommitteeMeeting, 
#     CommitteeMeetingAttendance, CommitteeDecision, CommitteeGRCLink
# )

# @admin.register(Committee)
# class CommitteeAdmin(admin.ModelAdmin):
#     list_display = ['name_en', 'committee_type', 'status', 'establishment_date']
#     list_filter = ['committee_type', 'status', 'meeting_frequency']
#     search_fields = ['name_en', 'name_ar', 'purpose']
#     readonly_fields = ['created_at', 'updated_at']

# @admin.register(CommitteeMember)
# class CommitteeMemberAdmin(admin.ModelAdmin):
#     list_display = ['committee', 'user', 'role', 'membership_status']
#     list_filter = ['role', 'membership_status', 'voting_rights']
#     search_fields = ['user__first_name', 'user__last_name']

# @admin.register(CommitteeMeeting)
# class CommitteeMeetingAdmin(admin.ModelAdmin):
#     list_display = ['committee', 'title', 'start_datetime', 'status']
#     list_filter = ['status', 'mode']
#     search_fields = ['title', 'agenda']

# @admin.register(CommitteeMeetingAttendance)
# class CommitteeMeetingAttendanceAdmin(admin.ModelAdmin):
#     list_display = ['meeting', 'member', 'status']
#     list_filter = ['status']

# @admin.register(CommitteeDecision)
# class CommitteeDecisionAdmin(admin.ModelAdmin):
#     list_display = ['meeting', 'title', 'status', 'effective_date']
#     list_filter = ['status']
#     search_fields = ['title', 'description']

# @admin.register(CommitteeGRCLink)
# class CommitteeGRCLinkAdmin(admin.ModelAdmin):
#     list_display = ['committee', 'entity_type', 'entity_id', 'linked_date']  # Fixed: 'linked_date' not 'linked_date'
#     list_filter = ['entity_type']
#     readonly_fields = ['linked_date']  # Make it read-only since it's auto_now_add