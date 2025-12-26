"""
视图层和API端点测试
"""

import pytest
from django.test import Client
from django.urls import reverse

from gameplay.services import ensure_manor


@pytest.fixture
def authenticated_client(django_user_model):
    """返回已登录的测试客户端"""
    user = django_user_model.objects.create_user(
        username="testplayer",
        password="testpass123"
    )
    client = Client()
    client.login(username="testplayer", password="testpass123")
    client.user = user
    return client


@pytest.fixture
def manor_with_user(authenticated_client):
    """返回带庄园的用户"""
    manor = ensure_manor(authenticated_client.user)
    return manor, authenticated_client


# ============ 核心页面测试 ============

@pytest.mark.django_db
class TestCoreViews:
    """核心页面视图测试"""

    def test_home_page_anonymous(self, client):
        """匿名用户访问首页"""
        response = client.get(reverse("home"))
        assert response.status_code == 200

    def test_home_page_authenticated(self, authenticated_client):
        """登录用户访问首页"""
        ensure_manor(authenticated_client.user)
        response = authenticated_client.get(reverse("home"))
        assert response.status_code == 200
        assert "manor" in response.context

    def test_dashboard_requires_login(self, client):
        """仪表盘需要登录"""
        response = client.get(reverse("gameplay:dashboard"))
        assert response.status_code == 302  # 重定向到登录

    def test_dashboard_authenticated(self, manor_with_user):
        """登录用户访问仪表盘"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:dashboard"))
        assert response.status_code == 200
        assert "buildings" in response.context

    def test_settings_page(self, manor_with_user):
        """设置页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:settings"))
        assert response.status_code == 200

    def test_ranking_page(self, manor_with_user):
        """排行榜页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:ranking"))
        assert response.status_code == 200
        assert "ranking" in response.context


# ============ 任务系统测试 ============

@pytest.mark.django_db
class TestMissionViews:
    """任务系统视图测试"""

    def test_task_board_page(self, manor_with_user):
        """任务面板页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:tasks"))
        assert response.status_code == 200
        assert "missions" in response.context

    def test_task_board_with_mission_selected(self, manor_with_user):
        """选择任务后的任务面板"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:tasks") + "?mission=huashan_lunjian")
        assert response.status_code == 200


# ============ 仓库系统测试 ============

@pytest.mark.django_db
class TestInventoryViews:
    """仓库系统视图测试"""

    def test_warehouse_page(self, manor_with_user):
        """仓库页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:warehouse"))
        assert response.status_code == 200
        assert "inventory_items" in response.context

    def test_warehouse_treasury_tab(self, manor_with_user):
        """仓库藏宝阁标签页"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:warehouse") + "?tab=treasury")
        assert response.status_code == 200
        assert response.context["current_tab"] == "treasury"

    def test_recruitment_hall_page(self, manor_with_user):
        """招募大厅页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:recruitment_hall"))
        assert response.status_code == 200
        assert "pools" in response.context


# ============ 消息系统测试 ============

@pytest.mark.django_db
class TestMessageViews:
    """消息系统视图测试"""

    def test_messages_page(self, manor_with_user):
        """消息列表页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:messages"))
        assert response.status_code == 200
        assert "message_list" in response.context

    def test_mark_all_read(self, manor_with_user):
        """标记全部已读"""
        manor, client = manor_with_user
        response = client.post(reverse("gameplay:mark_all_messages_read"))
        assert response.status_code == 302  # 重定向回消息列表


# ============ 科技系统测试 ============

@pytest.mark.django_db
class TestTechnologyViews:
    """科技系统视图测试"""

    def test_technology_page(self, manor_with_user):
        """科技页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:technology"))
        assert response.status_code == 200
        assert "technologies" in response.context

    def test_technology_martial_tab(self, manor_with_user):
        """武艺科技标签页"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:technology") + "?tab=martial")
        assert response.status_code == 200
        assert response.context["current_tab"] == "martial"


# ============ 生产系统测试 ============

@pytest.mark.django_db
class TestProductionViews:
    """生产系统视图测试"""

    def test_stable_page(self, manor_with_user):
        """马房页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:stable"))
        assert response.status_code == 200
        assert "horse_options" in response.context

    def test_ranch_page(self, manor_with_user):
        """畜牧场页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:ranch"))
        assert response.status_code == 200
        assert "livestock_options" in response.context

    def test_smithy_page(self, manor_with_user):
        """冶炼坊页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:smithy"))
        assert response.status_code == 200
        assert "metal_options" in response.context

    def test_forge_page(self, manor_with_user):
        """铁匠铺页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:forge"))
        assert response.status_code == 200
        assert "equipment_list" in response.context


# ============ 打工系统测试 ============

@pytest.mark.django_db
class TestWorkViews:
    """打工系统视图测试"""

    def test_work_page(self, manor_with_user):
        """打工页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:work"))
        assert response.status_code == 200
        assert "works" in response.context

    def test_work_tier_filter(self, manor_with_user):
        """打工等级过滤"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:work") + "?tier=senior")
        assert response.status_code == 200
        assert response.context["current_tier"] == "senior"


# ============ 募兵系统测试 ============

@pytest.mark.django_db
class TestRecruitmentViews:
    """募兵系统视图测试"""

    def test_troop_recruitment_page(self, manor_with_user):
        """募兵页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:troop_recruitment"))
        assert response.status_code == 200
        assert "recruitment_options" in response.context


# ============ 地图系统测试 ============

@pytest.mark.django_db
class TestMapViews:
    """地图系统视图测试"""

    def test_map_page(self, manor_with_user):
        """地图页面"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:map"))
        assert response.status_code == 200
        assert "regions" in response.context

    def test_map_region_filter(self, manor_with_user):
        """地图地区过滤"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:map") + "?region=beijing")
        assert response.status_code == 200
        assert response.context["selected_region"] == "beijing"


# ============ API 测试 ============

@pytest.mark.django_db
class TestMapAPI:
    """地图API测试"""

    def test_map_search_by_region(self, manor_with_user):
        """按地区搜索API"""
        manor, client = manor_with_user
        response = client.get(
            reverse("gameplay:map_search_api"),
            {"type": "region", "region": manor.region}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "results" in data

    def test_map_search_by_name(self, manor_with_user):
        """按名称搜索API"""
        manor, client = manor_with_user
        response = client.get(
            reverse("gameplay:map_search_api"),
            {"type": "name", "q": "test"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_protection_status_api(self, manor_with_user):
        """保护状态API"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:protection_status_api"))
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "protection" in data

    def test_raid_status_api(self, manor_with_user):
        """出征状态API"""
        manor, client = manor_with_user
        response = client.get(reverse("gameplay:raid_status_api"))
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "active_raids" in data

    def test_manor_detail_api(self, manor_with_user):
        """庄园详情API"""
        manor, client = manor_with_user
        response = client.get(
            reverse("gameplay:manor_detail_api", kwargs={"manor_id": manor.id})
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "manor" in data

    def test_manor_detail_api_not_found(self, manor_with_user):
        """庄园详情API - 不存在"""
        manor, client = manor_with_user
        response = client.get(
            reverse("gameplay:manor_detail_api", kwargs={"manor_id": 99999})
        )
        assert response.status_code == 404


# ============ POST 操作测试 ============

@pytest.mark.django_db
class TestPostOperations:
    """POST操作测试"""

    def test_upgrade_building(self, manor_with_user):
        """建筑升级"""
        manor, client = manor_with_user
        manor.grain = manor.silver = 100000
        manor.save()
        building = manor.buildings.first()
        response = client.post(
            reverse("gameplay:upgrade_building", kwargs={"pk": building.pk})
        )
        assert response.status_code == 302  # 重定向

    def test_delete_messages_empty(self, manor_with_user):
        """删除消息 - 空选择"""
        manor, client = manor_with_user
        response = client.post(reverse("gameplay:delete_messages"))
        assert response.status_code == 302


# ============ 权限测试 ============

@pytest.mark.django_db
class TestPermissions:
    """权限测试"""

    def test_protected_pages_redirect(self, client):
        """受保护页面重定向到登录"""
        protected_urls = [
            reverse("gameplay:dashboard"),
            reverse("gameplay:tasks"),
            reverse("gameplay:warehouse"),
            reverse("gameplay:messages"),
            reverse("gameplay:technology"),
            reverse("gameplay:work"),
            reverse("gameplay:stable"),
            reverse("gameplay:map"),
        ]
        for url in protected_urls:
            response = client.get(url)
            assert response.status_code == 302, f"{url} should redirect"

    def test_api_requires_login(self, client):
        """API需要登录"""
        api_urls = [
            reverse("gameplay:map_search_api"),
            reverse("gameplay:raid_status_api"),
            reverse("gameplay:protection_status_api"),
        ]
        for url in api_urls:
            response = client.get(url)
            assert response.status_code == 302, f"{url} should redirect"
