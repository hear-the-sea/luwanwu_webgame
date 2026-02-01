"""
帮会核心视图：大厅、列表、创建、详情
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q

from core.utils import safe_int, safe_ordering
from ..constants import GUILD_CREATION_COST, GUILD_HALL_DISPLAY_LIMIT, GUILD_LIST_PAGE_SIZE
from ..decorators import require_guild_leader
from ..models import Guild
from ..services import guild as guild_service
from gameplay.models import Manor


@login_required
def guild_hall(request):
    """帮会大厅 - 入口页面"""
    user = request.user

    # 检查是否已加入帮会
    if hasattr(user, 'guild_membership') and user.guild_membership.is_active:
        # 已加入帮会，重定向到帮会详情
        return redirect('guilds:detail', guild_id=user.guild_membership.guild.id)

    # 未加入帮会，显示帮会列表（使用 with_member_count 优化 N+1）
    guilds = Guild.objects.with_member_count().filter(is_active=True).order_by('-level', '-created_at')[:GUILD_HALL_DISPLAY_LIMIT]

    context = {
        'guilds': guilds,
        'can_create': True,
    }

    return render(request, 'guilds/hall.html', context)


@login_required
def guild_list(request):
    """帮会列表"""
    ordering = safe_ordering(request.GET.get('ordering', '-level'), '-level')
    search = request.GET.get('search', '')
    page = safe_int(request.GET.get('page', 1), default=1, min_val=1)
    page_size = GUILD_LIST_PAGE_SIZE

    guilds = guild_service.get_guild_list(
        ordering=ordering,
        search=search,
        page=page,
        page_size=page_size
    )

    context = {
        'guilds': guilds,
        'ordering': ordering,
        'search': search,
        'page': page,
    }

    return render(request, 'guilds/list.html', context)


@login_required
def guild_search(request):
    """搜索帮会"""
    query = request.GET.get('q', '')

    if query:
        # 使用 with_member_count 优化 N+1
        guilds = Guild.objects.with_member_count().filter(
            Q(name__icontains=query) & Q(is_active=True)
        ).order_by('-level')[:10]
    else:
        guilds = []

    context = {
        'guilds': guilds,
        'query': query,
    }

    return render(request, 'guilds/search.html', context)


@login_required
def create_guild(request):
    """创建帮会"""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        emblem = request.POST.get('emblem', 'default')

        try:
            guild = guild_service.create_guild(
                user=request.user,
                name=name,
                description=description,
                emblem=emblem
            )
            messages.success(request, f'恭喜！帮会【{guild.name}】创建成功！')
            return redirect('guilds:detail', guild_id=guild.id)
        except ValueError as e:
            messages.error(request, str(e))

    # GET请求，显示创建表单
    manor = get_object_or_404(Manor, user=request.user)

    # 获取金条数量（从仓库）
    from gameplay.models import InventoryItem, ItemTemplate
    try:
        gold_bar_template = ItemTemplate.objects.get(key='gold_bar')
        gold_bar_item = InventoryItem.objects.filter(
            manor=manor,
            template=gold_bar_template,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        ).first()
        gold_bar_count = gold_bar_item.quantity if gold_bar_item else 0
    except ItemTemplate.DoesNotExist:
        gold_bar_count = 0

    context = {
        'manor': manor,
        'gold_bar_count': gold_bar_count,
        'creation_cost': GUILD_CREATION_COST,
    }

    return render(request, 'guilds/create.html', context)


@login_required
def guild_detail(request, guild_id):
    """帮会详情页面"""
    guild = get_object_or_404(Guild, id=guild_id, is_active=True)
    user = request.user

    # 检查是否是本帮会成员
    is_member = False
    member = None
    if hasattr(user, 'guild_membership') and user.guild_membership.is_active:
        if user.guild_membership.guild == guild:
            is_member = True
            member = user.guild_membership

    # 获取帮会信息 - 优化查询，预加载成员数据减少 N+1
    leader = guild.get_leader()
    admins = guild.get_admins()
    members = guild.members.filter(is_active=True).select_related('user__manor').only(
        'id', 'position', 'joined_at', 'total_contribution', 'is_active',
        'user__id', 'user__username',
        'user__manor__id', 'user__manor__name'
    )[:20]
    announcements = guild.announcements.select_related("author").only(
        'id', 'type', 'content', 'created_at',
        'author__id', 'author__username'
    )[:5]

    # 获取科技信息
    technologies = None
    if is_member:
        technologies = guild.technologies.only('id', 'tech_key', 'level', 'category', 'max_level')

    context = {
        'guild': guild,
        'is_member': is_member,
        'member': member,
        'leader': leader,
        'admins': admins,
        'members': members,
        'announcements': announcements,
        'technologies': technologies,
    }

    return render(request, 'guilds/detail.html', context)


@login_required
@require_guild_leader
def guild_info(request, guild_id):
    """帮会信息设置"""
    guild = get_object_or_404(Guild, id=guild_id, is_active=True)
    member = request.guild_member

    # 验证是否为本帮会成员（防止跨帮会越权）
    if member.guild_id != guild.id:
        messages.error(request, '您不是该帮会成员')
        return redirect('guilds:detail', guild_id=member.guild_id)

    if request.method == 'POST':
        description = request.POST.get('description', '').strip()
        auto_accept = request.POST.get('auto_accept') == 'on'

        guild.description = description
        guild.auto_accept = auto_accept
        guild.save(update_fields=['description', 'auto_accept'])

        messages.success(request, '帮会信息已更新')
        return redirect('guilds:detail', guild_id=guild.id)

    context = {
        'guild': guild,
    }

    return render(request, 'guilds/info.html', context)
