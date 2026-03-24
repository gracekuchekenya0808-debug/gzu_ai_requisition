from django.contrib import admin
from .models import Item, Requisition, RequisitionItem, Approval, Fulfillment

class RequisitionItemInline(admin.TabularInline):
    model = RequisitionItem
    extra = 1

@admin.register(Requisition)
class RequisitionAdmin(admin.ModelAdmin):
    inlines = [RequisitionItemInline]
    list_display = ('id','requester','status','created')

admin.site.register(Item)
admin.site.register(Approval)
admin.site.register(Fulfillment)

# Register your models here.
