# guilds/urls.py

from django.urls import path
from . import views

app_name = 'guilds'

urlpatterns = [
    # 帮会大厅
    path('', views.guild_hall, name='hall'),

    # 帮会列表与搜索
    path('list/', views.guild_list, name='list'),
    path('search/', views.guild_search, name='search'),

    # 创建帮会
    path('create/', views.create_guild, name='create'),

    # 帮会详情
    path('<int:guild_id>/', views.guild_detail, name='detail'),
    path('<int:guild_id>/info/', views.guild_info, name='info'),

    # 申请与审批
    path('<int:guild_id>/apply/', views.apply_to_guild, name='apply'),
    path('applications/', views.application_list, name='applications'),
    path('application/<int:app_id>/approve/', views.approve_application, name='approve_application'),
    path('application/<int:app_id>/reject/', views.reject_application, name='reject_application'),

    # 成员管理
    path('members/', views.member_list, name='members'),
    path('member/<int:member_id>/kick/', views.kick_member, name='kick_member'),
    path('member/<int:member_id>/appoint/', views.appoint_admin, name='appoint_admin'),
    path('member/<int:member_id>/demote/', views.demote_admin, name='demote_admin'),
    path('member/<int:member_id>/transfer/', views.transfer_leadership, name='transfer_leadership'),
    path('leave/', views.leave_guild, name='leave'),

    # 帮会升级
    path('upgrade/', views.upgrade_guild, name='upgrade'),
    path('disband/', views.disband_guild, name='disband'),

    # 贡献系统
    path('donate/', views.donate_resource, name='donate'),
    path('contribution/ranking/', views.contribution_ranking, name='contribution_ranking'),

    # 科技系统
    path('technology/', views.technology_list, name='technology'),
    path('technology/<str:tech_key>/upgrade/', views.upgrade_technology, name='upgrade_tech'),

    # 仓库与兑换
    path('warehouse/', views.warehouse, name='warehouse'),
    path('warehouse/<str:item_key>/exchange/', views.exchange_item, name='exchange_item'),
    path('warehouse/logs/', views.exchange_logs, name='exchange_logs'),

    # 公告
    path('announcements/', views.announcement_list, name='announcements'),
    path('announcement/create/', views.create_announcement, name='create_announcement'),

    # 资源与日志
    path('resources/', views.resource_status, name='resources'),
    path('logs/donation/', views.donation_logs, name='donation_logs'),
    path('logs/resource/', views.resource_logs, name='resource_logs'),
]
