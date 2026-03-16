from __future__ import annotations

from django.core.management.base import BaseCommand

from gameplay.services.runtime_configs import format_runtime_config_summary, reload_runtime_configs


class Command(BaseCommand):
    help = "刷新运行期 YAML 配置缓存（商铺/拍卖/仓库/锻造/生产/门客成长/竞技场/交易/帮会规则）。"

    def handle(self, *args, **options):
        summary = reload_runtime_configs()
        self.stdout.write(self.style.SUCCESS(f"[OK] 运行期配置已刷新: {format_runtime_config_summary(summary)}"))
        self.stdout.write(
            self.style.WARNING(
                "Note: module-level constants in views and selectors (imported via 'from X import Y') "
                "will not reflect the new values until the process is restarted. "
                "Business logic service functions are updated."
            )
        )
