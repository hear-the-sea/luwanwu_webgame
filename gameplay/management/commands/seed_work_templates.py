from django.core.management.base import BaseCommand
from gameplay.models import WorkTemplate


class Command(BaseCommand):
    help = '初始化工作模板数据'

    def handle(self, *args, **options):
        if WorkTemplate.objects.exists():
            self.stdout.write(self.style.WARNING('工作模板数据已存在，跳过初始化'))
            return

        works = [
            # 初级工作区（2小时 = 7200秒）
            WorkTemplate(key="jiulou", name="酒楼", description="城市中的酒楼，因物廉价满生意很好，每天都在招募人手。", tier="junior", required_level=3, required_force=0, required_intellect=0, reward_silver=1000, work_duration=7200, display_order=1),
            WorkTemplate(key="yiguan", name="医馆", description="一家老字号的医馆叫济世堂，目前正在招募学徒。", tier="junior", required_level=5, required_force=0, required_intellect=0, reward_silver=1500, work_duration=7200, display_order=2),
            WorkTemplate(key="yizhan", name="驿站", description="驿站是传递宫府文书、情报的人或来往官员途中食宿，换马的场所，目前正在招募送递使者。", tier="junior", required_level=7, required_force=0, required_intellect=0, reward_silver=2000, work_duration=7200, display_order=3),
            WorkTemplate(key="shuyuan", name="书院", description="书院为乐育人才之地，希望有文德兼美之士入院职教。", tier="junior", required_level=9, required_force=0, required_intellect=0, reward_silver=2500, work_duration=7200, display_order=4),
            WorkTemplate(key="chaguan", name="茶馆", description="上午卖清茶，下午和晚上请艺人临场说评书，茶客边听书，边饮茶，倒也优哉游哉，乐乐陶陶。", tier="junior", required_level=11, required_force=0, required_intellect=0, reward_silver=3000, work_duration=7200, display_order=5),
            WorkTemplate(key="matou", name="码头", description="码头是商人用货船卸货的地方，人来人往非常的热闹繁忙！", tier="junior", required_level=13, required_force=0, required_intellect=0, reward_silver=3500, work_duration=7200, display_order=6),

            # 中级工作区（3小时 = 10800秒）
            WorkTemplate(key="wuguan", name="武馆", description="城中武馆招募陪练，需要一定武艺基础。", tier="intermediate", required_level=14, required_force=0, required_intellect=0, reward_silver=4000, work_duration=10800, display_order=1),
            WorkTemplate(key="shanghang", name="商行", description="大型商行招募账房和伙计，需要处理复杂账目。", tier="intermediate", required_level=15, required_force=0, required_intellect=0, reward_silver=4500, work_duration=10800, display_order=2),
            WorkTemplate(key="guanfu", name="官府", description="地方官府招募文书，协助处理政务。", tier="intermediate", required_level=16, required_force=0, required_intellect=0, reward_silver=5000, work_duration=10800, display_order=3),
            WorkTemplate(key="qianzhuang", name="钱庄", description="城中钱庄招募护卫和账房，待遇优渥。", tier="intermediate", required_level=17, required_force=0, required_intellect=0, reward_silver=5500, work_duration=10800, display_order=4),

            # 高级工作区（4小时 = 14400秒）
            WorkTemplate(key="biaoju", name="镖局", description="城中一家镖局目前正在扩大规模，目前正在招募武艺高强的镖师。", tier="senior", required_level=18, required_force=0, required_intellect=0, reward_silver=6000, work_duration=14400, display_order=1),
            WorkTemplate(key="jingwumeng", name="精武盟", description="精武盟势力分部全国，成员皆为武艺高强之辈，为武林中最强势力。", tier="senior", required_level=23, required_force=0, required_intellect=0, reward_silver=7000, work_duration=14400, display_order=2),
            WorkTemplate(key="shenfengyi", name="神风驿", description="神风驿为全国最高等级驿站，送递情报日行千里。", tier="senior", required_level=28, required_force=0, required_intellect=0, reward_silver=8000, work_duration=14400, display_order=3),
            WorkTemplate(key="guozijian", name="国子监", description="国子监全国中央官学，为国内教育体系中的最高学府。", tier="senior", required_level=33, required_force=0, required_intellect=0, reward_silver=9000, work_duration=14400, display_order=4),
        ]

        WorkTemplate.objects.bulk_create(works)

        self.stdout.write(self.style.SUCCESS(f'成功创建 {len(works)} 个工作模板'))
        self.stdout.write(self.style.SUCCESS('初级工作区: 6个工作'))
        self.stdout.write(self.style.SUCCESS('中级工作区: 4个工作'))
        self.stdout.write(self.style.SUCCESS('高级工作区: 4个工作'))
