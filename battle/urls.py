from django.urls import path

from .views import BattleReportDetailView

app_name = "battle"

urlpatterns = [
    path("report/<int:pk>/", BattleReportDetailView.as_view(), name="report_detail"),
]
