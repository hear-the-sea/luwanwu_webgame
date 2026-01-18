"""
Django Management Command: battle_debug

战斗调试命令行工具
"""

from django.core.management.base import BaseCommand, CommandError

from battle_debugger.config import ConfigLoader
from battle_debugger.simulator import BattleSimulator


class Command(BaseCommand):
    help = '战斗调试工具 - 用于测试、调优和对比战斗系统参数'

    def add_arguments(self, parser):
        # 子命令
        subparsers = parser.add_subparsers(
            dest='subcommand',
            help='子命令'
        )

        # === simulate 子命令 ===
        simulate_parser = subparsers.add_parser(
            'simulate',
            help='运行单次战斗模拟'
        )
        simulate_parser.add_argument(
            '--preset',
            type=str,
            help='预设配置名称'
        )
        simulate_parser.add_argument(
            '--config',
            type=str,
            help='配置文件路径'
        )
        simulate_parser.add_argument(
            '--seed',
            type=int,
            help='随机种子（用于复现）'
        )
        simulate_parser.add_argument(
            '--repeat',
            type=int,
            default=1,
            help='重复次数（默认1次）'
        )
        simulate_parser.add_argument(
            '--verbose',
            action='store_true',
            help='显示详细战斗过程'
        )
        simulate_parser.add_argument(
            '--override',
            action='append',
            help='覆盖参数（格式: key=value），可多次使用'
        )

        # === presets 子命令 ===
        subparsers.add_parser(
            'presets',
            help='列出所有可用的预设配置'
        )

        # === tune 子命令（后续实现）===
        tune_parser = subparsers.add_parser(
            'tune',
            help='参数调优（网格搜索）'
        )
        tune_parser.add_argument(
            '--preset',
            type=str,
            help='预设配置名称'
        )
        tune_parser.add_argument(
            '--param',
            type=str,
            required=True,
            help='要调优的参数名'
        )
        tune_parser.add_argument(
            '--values',
            type=str,
            required=True,
            help='参数值列表（逗号分隔，如：20,22,24,26）'
        )
        tune_parser.add_argument(
            '--repeat',
            type=int,
            default=10,
            help='每个参数值重复次数（默认10次）'
        )

    def handle(self, *args, **options):
        subcommand = options.get('subcommand')

        if not subcommand:
            self.print_help('manage.py', 'battle_debug')
            return

        if subcommand == 'simulate':
            self.handle_simulate(options)
        elif subcommand == 'presets':
            self.handle_presets(options)
        elif subcommand == 'tune':
            self.handle_tune(options)
        else:
            raise CommandError(f'未知子命令: {subcommand}')

    def handle_simulate(self, options):
        """处理simulate子命令"""
        loader = ConfigLoader()

        # 加载配置
        config = None
        if options.get('preset'):
            try:
                config = loader.load_preset(options['preset'])
                self.stdout.write(
                    self.style.SUCCESS(f'✓ 加载预设配置: {options["preset"]}')
                )
            except FileNotFoundError as e:
                raise CommandError(str(e))

        elif options.get('config'):
            try:
                config = loader.load_yaml(options['config'])
                self.stdout.write(
                    self.style.SUCCESS(f'✓ 加载配置文件: {options["config"]}')
                )
            except FileNotFoundError:
                raise CommandError(f'配置文件不存在: {options["config"]}')
        else:
            raise CommandError('必须指定 --preset 或 --config')

        # 应用覆盖参数
        if options.get('override'):
            overrides = {}
            for override in options['override']:
                try:
                    key, value = override.split('=', 1)
                    # 尝试转换数值
                    try:
                        value = int(value)
                    except ValueError:
                        try:
                            value = float(value)
                        except ValueError:
                            pass  # 保持字符串
                    overrides[key] = value
                except ValueError:
                    raise CommandError(f'无效的覆盖参数格式: {override}')

            if overrides:
                config = loader.merge_config(config, overrides)
                self.stdout.write(
                    self.style.WARNING(f'✓ 应用参数覆盖: {overrides}')
                )

        # 校验配置
        errors = loader.validate(config)
        if errors:
            self.stdout.write(self.style.ERROR('配置错误:'))
            for error in errors:
                self.stdout.write(self.style.ERROR(f'  - {error}'))
            raise CommandError('配置校验失败')

        # 运行模拟
        simulator = BattleSimulator(config)
        seed = options.get('seed')
        repeat = options.get('repeat', 1)
        verbose = options.get('verbose', False)

        self.stdout.write(self.style.SUCCESS('\n' + '═' * 60))
        self.stdout.write(self.style.SUCCESS('开始战斗模拟'))
        self.stdout.write(self.style.SUCCESS('═' * 60))

        results = []
        for i in range(repeat):
            # 使用指定种子或自动生成
            current_seed = seed + i if seed is not None else None

            result = simulator.run_battle(seed=current_seed)
            results.append(result)

            if repeat == 1 or verbose:
                self.print_battle_result(result, config, verbose)
            else:
                # 批量模式，只显示简要信息
                winner_icon = "✓" if result["winner"] == "attacker" else "✗"
                self.stdout.write(
                    f'  [{i+1}/{repeat}] {winner_icon} '
                    f'种子:{result["seed"]} | '
                    f'胜者:{result["winner"]} | '
                    f'回合:{len(result["combat_log"])}'
                )

        # 显示统计
        if repeat > 1:
            self.print_statistics(results)

    def handle_presets(self, options):
        """处理presets子命令"""
        loader = ConfigLoader()
        presets = loader.list_presets()

        if not presets:
            self.stdout.write(self.style.WARNING('未找到预设配置'))
            return

        self.stdout.write(self.style.SUCCESS('\n可用的预设配置:'))
        self.stdout.write(self.style.SUCCESS('─' * 60))

        for preset in presets:
            info = loader.get_preset_info(preset)
            name = info.get('name', preset)
            desc = info.get('description', '无描述')
            self.stdout.write(f'  • {preset}')
            self.stdout.write(f'    名称: {name}')
            self.stdout.write(f'    描述: {desc}')
            self.stdout.write('')

    def handle_tune(self, options):
        """处理tune子命令（简化版）"""
        loader = ConfigLoader()

        # 加载配置
        if not options.get('preset'):
            raise CommandError('必须指定 --preset')

        try:
            config = loader.load_preset(options['preset'])
        except FileNotFoundError as e:
            raise CommandError(str(e))

        # 解析参数值
        param_name = options['param']
        values_str = options['values']
        try:
            values = [float(v.strip()) for v in values_str.split(',')]
        except ValueError:
            raise CommandError(f'无效的参数值列表: {values_str}')

        repeat = options.get('repeat', 10)

        self.stdout.write(self.style.SUCCESS('\n' + '═' * 60))
        self.stdout.write(self.style.SUCCESS('参数调优'))
        self.stdout.write(self.style.SUCCESS('═' * 60))
        self.stdout.write(f'参数: {param_name}')
        self.stdout.write(f'值列表: {values}')
        self.stdout.write(f'重复次数: {repeat}')
        self.stdout.write('')

        # 运行调优
        results_by_value = {}

        for value in values:
            # 设置参数
            config.tunable_params[param_name] = value

            # 运行多次模拟
            results = []
            for i in range(repeat):
                simulator = BattleSimulator(config)
                result = simulator.run_battle()
                results.append(result)

            results_by_value[value] = results

            # 显示进度
            attacker_wins = sum(1 for r in results if r["winner"] == "attacker")
            win_rate = attacker_wins / repeat * 100
            avg_rounds = sum(len(r["combat_log"]) for r in results) / repeat

            self.stdout.write(
                f'  {param_name}={value}: '
                f'胜率={win_rate:.1f}% | '
                f'平均回合={avg_rounds:.1f}'
            )

        self.stdout.write('\n' + '═' * 60)

    def print_battle_result(self, result, config, verbose=False):
        """打印战斗结果"""
        self.stdout.write('\n配置: ' + config.name)
        if config.description:
            self.stdout.write('描述: ' + config.description)
        self.stdout.write(f'种子: {result["seed"]}')
        self.stdout.write('─' * 60)

        # 胜负
        winner = result["winner"]
        winner_text = "攻方" if winner == "attacker" else "守方"
        winner_style = self.style.SUCCESS if winner == "attacker" else self.style.WARNING
        self.stdout.write(winner_style(f'胜者: {winner_text}'))

        # 回合数
        rounds = len(result["combat_log"])
        self.stdout.write(f'回合: {rounds}')

        # 损失统计
        losses = result["losses"]
        if "attacker" in losses:
            atk_loss = losses["attacker"]
            self.stdout.write(
                f'攻方兵损: {atk_loss.get("troops_lost", 0)} / '
                f'{atk_loss.get("troops_deployed", 0)} '
                f'({atk_loss.get("hp_loss_percent", 0)}%)'
            )

        if "defender" in losses:
            def_loss = losses["defender"]
            self.stdout.write(
                f'守方兵损: {def_loss.get("troops_lost", 0)} / '
                f'{def_loss.get("troops_deployed", 0)} '
                f'({def_loss.get("hp_loss_percent", 0)}%)'
            )

        # 详细战斗过程
        if verbose:
            self.print_combat_log(result["combat_log"])

        self.stdout.write('═' * 60)

    def print_combat_log(self, combat_log):
        """打印战斗日志"""
        self.stdout.write('\n' + '─' * 60)
        self.stdout.write('战斗过程:')
        self.stdout.write('─' * 60)

        for round_data in combat_log[:10]:  # 最多显示前10回合
            round_no = round_data.get("round", "?")
            priority = round_data.get("priority")

            if priority is not None:
                phase_name = "先锋" if priority == -2 else "先攻"
                self.stdout.write(f'\n━━━ 回合 {round_no} ({phase_name}阶段) ━━━')
            else:
                self.stdout.write(f'\n━━━ 回合 {round_no} ━━━')

            events = round_data.get("events", [])
            for i, event in enumerate(events[:5]):  # 每回合最多显示5个事件
                if event.get("status") == "charging":
                    continue

                actor = event.get("actor", "?")
                target = event.get("target", "?")
                damage = event.get("damage", 0)
                kills = event.get("kills", 0)
                skills = event.get("skills", [])

                skill_text = f' | 技能:{skills}' if skills else ''
                crit_text = ' | 暴击' if event.get("is_crit") else ''

                self.stdout.write(
                    f'  [{i+1}] {actor} → {target} | '
                    f'伤害:{damage} | 击杀:{kills}'
                    f'{skill_text}{crit_text}'
                )

            if len(events) > 5:
                self.stdout.write(f'  ... (还有{len(events)-5}个事件)')

        if len(combat_log) > 10:
            self.stdout.write(f'\n... (还有{len(combat_log)-10}回合)')

    def print_statistics(self, results):
        """打印统计信息"""
        self.stdout.write('\n' + '═' * 60)
        self.stdout.write(self.style.SUCCESS('统计信息'))
        self.stdout.write('═' * 60)

        total = len(results)
        attacker_wins = sum(1 for r in results if r["winner"] == "attacker")
        defender_wins = total - attacker_wins

        avg_rounds = sum(len(r["combat_log"]) for r in results) / total

        self.stdout.write(f'总模拟次数: {total}')
        self.stdout.write(f'攻方胜利: {attacker_wins} ({attacker_wins/total*100:.1f}%)')
        self.stdout.write(f'守方胜利: {defender_wins} ({defender_wins/total*100:.1f}%)')
        self.stdout.write(f'平均回合: {avg_rounds:.1f}')
        self.stdout.write('═' * 60)
