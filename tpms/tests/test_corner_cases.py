import pytest

try:
    from processor.config_manager import ConfigManager
    from processor.tagger import ModelTagger
except ImportError:
    from tpms.processor.config_manager import ConfigManager
    from tpms.processor.tagger import ModelTagger


def test_corner_cases():
    cm = ConfigManager()
    cm.sheet_rules = {
        '爆胎': {
            'full_models': {'EWEK-10型', 'EWEK-10', 'CKEB-30型', 'CKEB-30', 'UNEH-30型'},
            'code_pairs': [('EWEK', '10'), ('CKEB', '30'), ('EWEL', '5'), ('SNED', ''), ('UNEH', '30')]
        },
        '独立控制器': {
            'full_models': {'SEAL-08型', 'UNHG-30型'},
            'code_pairs': [('SEAL', '8'), ('UNHG', '30')]
        },
        '直接式': {
            'full_models': {'STEAY尊贵型', 'UNED-30型', 'UNHD-10型'},
            'code_pairs': [('STEAY', ''), ('UNED', '30'), ('UNHD', '10')]
        }
    }
    cm.countries = ['日本', '沙特', '哥斯达黎加', '泰国', '澳大利亚', '澳洲', '德国']
    tagger = ModelTagger(cm)

    test_cases = [
        ('CKEB', '(CKEB-30型-右舵-日标充电-日本79091)', '出口', 'contains CKEB-30型 and Japan - country is priority 1'),
        ('CKEB', 'CKEB-30型-右舵-日标充电-日本', '出口', 'contains CKEB-30型 without brackets and Japan - country is priority 1'),
        ('CKEB', '(CKEB-30型-国标充电-79091)', '爆胎', 'contains CKEB-30型 without country - spec is priority 2'),
        ('CKEB', '(CKEB-40型-右舵-日标充电-日本79062/79064)', '出口', 'CKEB-40 not in baotai, but Japan is country'),
        ('CKEFX', '(CKEFX-40型-右舵-日标充电-哥斯达黎加122815/122814)', '出口', 'Costa Rica'),
        ('EWEK', '汉EV 605KM 尊贵型(EWEK-10型) 黑色', '爆胎', 'EWEK-10型 in brackets'),
        ('EWEK', '汉EV 605KM 尊贵型(EWEK-10) 黑色', '爆胎', 'EWEK-10 in brackets'),
        ('EWEK', '汉EV 605KM 尊贵型(EWEK-10") 黑色', '爆胎', 'EWEK-10" in brackets'),
        ('EWEK', '汉EV 605KM 尊贵型(-10型) 黑色', '爆胎', 'EWEK in prod, -10型 in model'),
        ('EWEK', '汉EV 605KM 尊贵型-10" 黑色', '爆胎', 'EWEK in prod, -10" in model'),
        ('EWEK', '汉EV 605KM 尊贵型 10型 黑色', '爆胎', 'EWEK in prod, 10型 in model'),
        ('EWEK', '汉EV 605KM 尊贵型 10 黑色', '', 'isolated 10 should NOT match'),
        ('EWEL', '元PLUS 510KM (EWEL-05型)', '爆胎', 'EWEL with 05 vs 5'),
        ('EWEL', '元PLUS 510KM (EWEL-5型)', '爆胎', 'EWEL with 5型'),
        ('SNED', '唐DM-i 112KM (SNED-右舵-澳洲)', '出口', 'SNED with 澳洲 - country is priority 1'),
        ('SNED', '唐DM-i 112KM (SNED-10型)', '爆胎', 'SNED with 10型 without country - spec is priority 2'),
        ('SNED', 'SNED-旗舰型', '爆胎', 'SNED empty secondary code in baotai'),
        ('CKEB', '直接式胎压监测 CKEB', '直接式', 'direct tag in model'),
        ('UNKNOWN', '未知车型-普通款', '', 'unmatched'),
        # 真实图片对应噪声车型边界测试
        ('STEAY', 'STEAY尊贵型Y', '直接式', 'STEAY尊贵型 with trailing Y'),
        ('UNED', 'UNED-30型(普通)', '直接式', 'UNED-30型 with (普通)'),
        ('UNEH', 'UNEH-30型(选装激光雷达)', '爆胎', 'UNEH-30型 with (选装激光雷达)'),
        ('UNHD', 'UNHD-10型试验', '直接式', 'UNHD-10型 with 试验'),
        ('UNHG', 'UNHG-30型(选装激光雷达)试验', '独立控制器', 'UNHG-30型 with lidar and test'),
    ]

    failures = []
    for prod, model, expected, desc in test_cases:
        res, prio = tagger.evaluate_row(prod, model)
        if res != expected:
            failures.append(f"Failed: {desc} -> got '{res}', expected '{expected}'")

    assert not failures, "\n".join(failures)


def test_country_list_contains_all_world_countries(tmp_path):
    """验证国家列表涵盖联合国全部 193 个成员国、2 个观察员国以及关键贸易地区与领地"""
    country_xlsx = str(tmp_path / "国家列表.xlsx")
    ConfigManager.create_default_country_list(country_xlsx)

    cm = ConfigManager()
    countries = cm.load_country_list(country_xlsx)

    un_193_members = [
        # Africa (54)
        '阿尔及利亚', '安哥拉', '贝宁', '博茨瓦纳', '布基纳法索', '布隆迪', '佛得角', '喀麦隆', '中非', '乍得',
        '科摩罗', '刚果共和国', '刚果民主共和国', '科特迪瓦', '吉布提', '埃及', '赤道几内亚', '厄立特里亚', '斯威士兰', '埃塞俄比亚',
        '加蓬', '冈比亚', '加纳', '几内亚', '几内亚比绍', '肯尼亚', '莱索托', '利比里亚', '利比亚', '马达加斯加',
        '马拉维', '马里', '毛里塔尼亚', '毛里求斯', '摩洛哥', '莫桑比克', '纳米比亚', '尼日尔', '尼日利亚', '卢旺达',
        '圣多美和普林西比', '塞内加尔', '塞舌尔', '塞拉利昂', '索马里', '南非', '南苏丹', '苏丹', '坦桑尼亚', '多哥',
        '突尼斯', '乌干达', '赞比亚', '津巴布韦',
        # Americas (35)
        '安提瓜和巴布达', '阿根廷', '巴哈马', '巴巴多斯', '伯利兹', '玻利维亚', '巴西', '加拿大', '智利', '哥伦比亚',
        '哥斯达黎加', '古巴', '多米尼克', '多米尼加', '厄瓜多尔', '萨尔瓦多', '格林纳达', '危地马拉', '圭亚那', '海地',
        '洪都拉斯', '牙买加', '墨西哥', '尼加拉瓜', '巴拿马', '巴拉圭', '秘鲁', '圣基茨和尼维斯', '圣卢西亚', '圣文森特和格林纳丁斯',
        '苏里南', '特立尼达和多巴哥', '美国', '乌拉圭', '委内瑞拉',
        # Asia (47)
        '阿富汗', '亚美尼亚', '阿塞拜疆', '巴林', '孟加拉国', '不丹', '文莱', '柬埔寨', '塞浦路斯',
        '格鲁吉亚', '印度', '印度尼西亚', '伊朗', '伊拉克', '以色列', '日本', '约旦', '哈萨克斯坦', '科威特',
        '吉尔吉斯斯坦', '老挝', '黎巴嫩', '马来西亚', '马尔代夫', '蒙古', '缅甸', '尼泊尔', '朝鲜', '阿曼',
        '巴基斯坦', '菲律宾', '卡塔尔', '韩国', '沙特阿拉伯', '新加坡', '斯里兰卡', '叙利亚', '塔吉克斯坦', '泰国',
        '东帝汶', '土耳其', '土库曼斯坦', '阿拉伯联合酋长国', '乌兹别克斯坦', '越南', '也门',
        # Europe (43)
        '阿尔巴尼亚', '安道尔', '奥地利', '白俄罗斯', '比利时', '波斯尼亚和黑塞哥维那', '保加利亚', '克罗地亚', '捷克', '丹麦',
        '爱沙尼亚', '芬兰', '法国', '德国', '希腊', '匈牙利', '冰岛', '爱尔兰', '意大利', '拉脱维亚',
        '列支敦士登', '立陶宛', '卢森堡', '马耳他', '摩尔多瓦', '摩纳哥', '黑山', '荷兰', '北马其顿', '挪威',
        '波兰', '葡萄牙', '罗马尼亚', '俄罗斯', '圣马力诺', '塞尔维亚', '斯洛伐克', '斯洛文尼亚', '西班牙', '瑞典',
        '瑞士', '乌克兰', '英国',
        # Oceania (14)
        '澳大利亚', '斐济', '基里巴斯', '马绍尔群岛', '密克罗尼西亚', '瑙鲁', '新西兰', '帕劳', '巴布亚新几内亚', '萨摩亚',
        '所罗门群岛', '汤加', '图瓦卢', '瓦努阿图'
    ]

    missing_members = [c for c in un_193_members if not any(c in item for item in countries)]
    assert not missing_members, f"国家列表中缺失以下联合国成员国: {missing_members}"

    # 观察员国与领地地区验证
    assert any('梵蒂冈' in c or '教廷' in c for c in countries)
    assert any('巴勒斯坦' in c for c in countries)
    assert any('库克' in c for c in countries)
    assert any('纽埃' in c for c in countries)
    assert any('科索沃' in c for c in countries)
    assert any('台湾' in c for c in countries)


def test_partial_row_short_name_or_full_name_only(tmp_path):
    """验证即使某一行只有简称或者只有全称，也可以被正确加入过滤名单并触发出口打标"""
    import pandas as pd
    custom_country_file = str(tmp_path / "自定义国家.xlsx")

    # 构造包含单列有效值的测试行
    df = pd.DataFrame([
        {'国家/地区': None, '常用中文简称': '特多', '官方全称/别名': None, '所属大洲': '美洲'},
        {'国家/地区': None, '常用中文简称': None, '官方全称/别名': '多米尼克国', '所属大洲': '美洲'},
        {'国家/地区': '纽埃', '常用中文简称': None, '官方全称/别名': None, '所属大洲': '大洋洲'},
        {'国家/地区': '圣卢西亚', '常用中文简称': '圣卢西亚', '官方全称/别名': '圣卢西亚', '所属大洲': '美洲'},
    ])
    df.to_excel(custom_country_file, index=False)

    cm = ConfigManager()
    cm.sheet_rules = {}
    countries = cm.load_country_list(custom_country_file)

    # 确保只有简称的行加入过滤名单
    assert '特多' in countries
    # 确保只有全称的行加入过滤名单
    assert '多米尼克国' in countries
    # 确保只有通称的行加入过滤名单
    assert '纽埃' in countries
    assert '圣卢西亚' in countries
    # 满足最新需求：出现国家/地区、常用中文简称、官方全称/别名、所属大洲（中国除外）均计入出口
    assert '美洲' in countries
    assert '大洋洲' in countries

    # 验证打标时能否正常根据提取出的单字段识别出口
    tagger = ModelTagger(cm)
    res1, prio1 = tagger.evaluate_row('CKEB', '海豚 智航版(特多专供)')
    assert res1 == '出口' and prio1 == 1

    res2, prio2 = tagger.evaluate_row('STEAY', 'STEAY-多米尼克国定制版')
    assert res2 == '出口' and prio2 == 1

    res3, prio3 = tagger.evaluate_row('UNED', 'UNED-30型(纽埃)')
    assert res3 == '出口' and prio3 == 1


def test_domestic_keywords_not_mistakenly_tagged(tmp_path):
    """验证国内本土车型词汇（如中国、国内等）不会误判为出口"""
    country_xlsx = str(tmp_path / "国家列表.xlsx")
    ConfigManager.create_default_country_list(country_xlsx)

    cm = ConfigManager()
    countries = cm.load_country_list(country_xlsx)

    assert '中国' not in countries
    assert '中华人民共和国' not in countries

    tagger = ModelTagger(cm)
    res, _ = tagger.evaluate_row('UNED', 'UNED-30型 中国特别纪念版')
    assert res != '出口'


def test_extracted_model_column_preserves_full_complete_information():
    """验证提取车型列到处理后文件表时，完整保存原始车型信息（不截断括号、选装配置、版本后缀及试验标识）"""
    import pandas as pd
    cm = ConfigManager()
    cm.sheet_rules = {
        '直接式': {
            'full_models': {'UNED-30型', 'STEAY尊贵型', 'UNHD-10型'},
            'code_pairs': [('UNED', '30'), ('STEAY', ''), ('UNHD', '10')]
        },
        '爆胎': {
            'full_models': {'UNEH-30型'},
            'code_pairs': [('UNEH', '30')]
        },
        '独立控制器': {
            'full_models': {'UNHG-30型'},
            'code_pairs': [('UNHG', '30')]
        }
    }
    tagger = ModelTagger(cm)

    original_models = [
        'STEAY尊贵型Y (2026款 高配版)',
        'UNED-30型(普通) 选配全景天窗',
        'UNEH-30型(选装激光雷达)',
        'UNHD-10型试验 研发样车',
        'UNHG-30型(选装激光雷达)试验车批次A'
    ]

    df_input = pd.DataFrame({
        '大车系': ['海鸥', '秦', '宋', '汉', '唐'],
        '生产车系': ['STEAY', 'UNED', 'UNEH', 'UNHD', 'UNHG'],
        '车型': original_models,
        '排产数量': [10, 20, 30, 40, 50]
    })

    df_output = tagger.tag_dataframe(df_input, drop_totals=True)

    # 1. 验证处理后输出表中的车型列必须 100% 完整保留原始文本
    assert df_output['车型'].tolist() == original_models

    # 2. 验证尽管车型列保留了完整复杂文字，配置列依然能够精准识别并打标
    expected_configs = ['直接式', '直接式', '爆胎', '直接式', '独立控制器']
    assert df_output['配置'].tolist() == expected_configs


def test_new_spec_auto_detect_headers_and_tag_ckeb30_as_direct_not_baotai(tmp_path):
    """验证用户选择新的标准参考文件后，自动检测表头一级代码和二级代码，并将 CKEB-30 正确打标为新规范（如直接式）而非旧规则（爆胎）"""
    import pandas as pd
    from processor.consolidator import DataConsolidator

    spec_path = str(tmp_path / "新车型分类规范.xlsx")
    with pd.ExcelWriter(spec_path, engine="openpyxl") as writer:
        # 模拟真实场景：第0行是说明标题栏，第1行是真实表头
        df_direct = pd.DataFrame([
            ["说明标题：本表为TPMS直接式车型技术规范", None, None],
            ["一级代码", "二级代码", "车型全称"],
            ["CKEB", "30", "CKEB-30型"],
            ["UNED", "20", "UNED-20型"]
        ])
        df_direct.to_excel(writer, sheet_name="直接式", header=False, index=False)

        df_indirect = pd.DataFrame([
            ["一级代码", "二级代码", "车型全称"],
            ["STHNY", "15", "STHNY-15型"]
        ])
        df_indirect.to_excel(writer, sheet_name="间接式", header=False, index=False)

    cm = ConfigManager()
    # 模拟之前残留的旧规则（旧规范里 CKEB-30 是爆胎）
    cm.sheet_rules = {
        '爆胎': {
            'code_pairs': [('CKEB', '30')],
            'full_models': {'CKEB-30型'}
        }
    }
    cm.countries = ['日本', '德国']
    tagger = ModelTagger(cm)

    # 验证旧规则下确实会打标为“爆胎”
    old_res, _ = tagger.evaluate_row("CKEB", "(CKEB-30型-国标充电-79091)")
    assert old_res == "爆胎"

    # 现在用户选择了“新车型分类规范.xlsx”，载入新规范
    rules = cm.load_model_spec(spec_path)
    assert "直接式" in rules
    assert "爆胎" not in rules  # 旧规则彻底清除
    tagger.set_config(cm)

    # 验证打标：CKEB-30 必须自动识别为新的标准“直接式”，绝不能是之前的“爆胎”
    new_res, prio = tagger.evaluate_row("CKEB", "(CKEB-30型-国标充电-79091)")
    assert new_res == "直接式"
    assert prio == 2


def test_new_spec_header_variants_yi_ji_er_ji(tmp_path):
    """验证各种表头变体（'一级'/'二级'、'一级车型'/'二级车型'、'车型代码(一级)'/'车型代码(二级)'等）自动检测"""
    import pandas as pd

    variants = [
        ("一级", "二级"),
        ("一级车型", "二级车型"),
        ("生产车系代码", "车型代码"),
        ("车系代码", "车型代码"),
        ("车型代码(一级)", "车型代码(二级)"),
        ("1级代码", "2级代码"),
    ]

    for idx, (col1, col2) in enumerate(variants):
        spec_path = str(tmp_path / f"规范变体_{idx}.xlsx")
        with pd.ExcelWriter(spec_path, engine="openpyxl") as writer:
            df = pd.DataFrame({
                col1: ["CKEB", "UNED"],
                col2: ["30", "20"],
                "车型名称": ["海豚CKEB-30", "UNED-20型"]
            })
            df.to_excel(writer, sheet_name="直接式", index=False)

        cm = ConfigManager()
        rules = cm.load_model_spec(spec_path)
        assert "直接式" in rules
        assert len(rules["直接式"]["code_pairs"]) >= 2
        assert ("CKEB", "30") in rules["直接式"]["code_pairs"]

        tagger = ModelTagger(cm)
        res, _ = tagger.evaluate_row("CKEB", "(CKEB-30型-国标充电-79091)")
        assert res == "直接式"


def test_single_sheet_with_config_column(tmp_path):
    """验证单Sheet（Sheet1）通过内置“配置”或“分类”列自动划分标准的组织架构"""
    import pandas as pd

    spec_path = str(tmp_path / "单工作表规范.xlsx")
    df = pd.DataFrame({
        "一级代码": ["CKEB", "STHNY", "UNHG"],
        "二级代码": ["30", "15", "30"],
        "配置分类": ["直接式", "间接式", "独立控制器"]
    })
    df.to_excel(spec_path, sheet_name="Sheet1", index=False)

    cm = ConfigManager()
    rules = cm.load_model_spec(spec_path)
    assert "直接式" in rules
    assert "间接式" in rules
    assert "独立控制器" in rules

    tagger = ModelTagger(cm)
    res_ckeb, _ = tagger.evaluate_row("CKEB", "(CKEB-30型-国标充电-79091)")
    assert res_ckeb == "直接式"

    res_sthny, _ = tagger.evaluate_row("STHNY", "STHNY-15型")
    assert res_sthny == "间接式"


def test_consolidator_overwrites_obsolete_config_column(tmp_path):
    """验证当输入文件已存在过期的‘配置’列（如旧规则打标的‘爆胎’）时，合并汇总时自动使用最新规范重新计算打标"""
    import pandas as pd
    from processor.consolidator import DataConsolidator

    spec_path = str(tmp_path / "新标准.xlsx")
    with pd.ExcelWriter(spec_path, engine="openpyxl") as writer:
        df_spec = pd.DataFrame({
            "一级代码": ["CKEB"],
            "二级代码": ["30"]
        })
        df_spec.to_excel(writer, sheet_name="直接式", index=False)

    cm = ConfigManager()
    cm.load_model_spec(spec_path)
    tagger = ModelTagger(cm)
    consolidator = DataConsolidator(tagger)

    # 准备一个包含过期“配置”列的已处理单基地月计划文件
    processed_input = str(tmp_path / "常州月计划_processed.xlsx")
    df_old_processed = pd.DataFrame({
        "大车系": ["CKE"],
        "生产车系": ["CKEB"],
        "车型": ["(CKEB-30型-国标充电-79091)"],
        "9月": [100],
        "配置": ["爆胎"]  # 这是旧标准产生的不正确结果
    })
    df_old_processed.to_excel(processed_input, sheet_name="车型汇总", index=False)

    # 执行汇总
    out_dir = str(tmp_path / "out")
    summary_path, df_summary = consolidator.consolidate_bases(
        file_paths=[processed_input],
        output_dir=out_dir,
        summary_filename="全基地汇总.xlsx"
    )

    # 验证汇总结果中的配置列必须被更新为当前新规范的“直接式”，绝不能是过期的“爆胎”
    assert df_summary.loc[0, "配置"] == "直接式"
    assert df_summary.loc[0, "配置"] != "爆胎"


def test_single_character_code_e_and_h_not_mistakenly_matching_ckeb(tmp_path):
    """
    针对用户现场拍摄的真实规范图片进行精准回归测试：
    规范中 Sheet '爆胎' 包含大量 '一级车型代码' 仅为单个字母 'E' 或 'H' 且 '二级车型代码' 为空的行（如 秦L-26款: E, 唐Pro26款: E, 海豹07换代: H）。
    验证：
    1. 生产车系为 CKEB 的车型，绝不能因为含有字母 E 而被误打标为 '爆胎'（命中出口日本，或按其自身规范打标）。
    2. 生产车系为 UNE、EWEK 的车型，绝不能因为含有字母 E 而被误匹配为 'E'。
    3. 生产车系真正为 'E' 或 'HA3H' 的车型，必须能准确匹配并打标为 '爆胎'。
    4. 生产车系真正为 'H' 的车型，必须能准确匹配并打标为 '爆胎'。
    """
    import pandas as pd

    spec_path = str(tmp_path / "真实爆胎规范表.xlsx")
    with pd.ExcelWriter(spec_path, engine="openpyxl") as writer:
        df_baotai = pd.DataFrame({
            "车型名称": ["钛7 改款", "宋GT-EV", "秦L-26款", "秦L-26款", "唐Pro26款", "唐Pro26款", "海豹07换代", "海豹07换代"],
            "一级车型代码": ["QZH-3T", "UFE", "HA3H", "E", "QBH", "E", "HX2E", "H"],
            "二级车型代码": ["", "", "", "", "", "", "", ""]
        })
        df_baotai.to_excel(writer, sheet_name="爆胎", index=False)

        # 另外直接式规范里有 CKEB-30
        df_direct = pd.DataFrame({
            "车型名称": ["海豚直接式款"],
            "一级车型代码": ["CKEB"],
            "二级车型代码": ["30"]
        })
        df_direct.to_excel(writer, sheet_name="直接式", index=False)

    cm = ConfigManager()
    cm.load_model_spec(spec_path)
    cm.countries = ["日本", "沙特", "德国"]
    tagger = ModelTagger(cm)

    # 1. 核心校验点：CKEB-30 未含出口国家时，按其自身规范打标为“直接式”，绝不是“爆胎”
    res_ckeb_30, pri_30 = tagger.evaluate_row("CKEB", "(CKEB-30型-国标充电-79091)")
    assert res_ckeb_30 == "直接式", f"CKEB-30 应该命中直接式规范，但得到了: {res_ckeb_30}"
    assert res_ckeb_30 != "爆胎"
    assert pri_30 == 2

    # 2. 如果包含“日本”，且国家为第一优先级，必须优先命中出口（优先级1）
    res_ckeb_jp, pri_jp = tagger.evaluate_row("CKEB", "(CKEB-30型-右舵-日标充电-日本79091)")
    assert res_ckeb_jp == "出口"
    assert pri_jp == 1

    # 3. 如果 CKEB-40 没在任何 TPMS 规范中，但含有“日本”，命中出口（优先级1），绝不能因为 E 被打标爆胎！
    res_ckeb_40, pri_40 = tagger.evaluate_row("CKEB", "(CKEB-40型-右舵-日标充电-日本79062/79064)")
    assert res_ckeb_40 == "出口", f"CKEB-40 应该命中出口，但得到了: {res_ckeb_40}"
    assert pri_40 == 1

    # 4. 生产车系为 UNE 或 EWEK 的车型，绝不能因为名字带 E 被误打标为爆胎
    res_une, _ = tagger.evaluate_row("UNE", "UNED-20型")
    assert res_une != "爆胎"

    # 5. 生产车系真正为 E 的秦L，必须准确命中爆胎（车型分类规范优先级2）
    res_e_qin, pri_e = tagger.evaluate_row("E", "秦L-26款 卓越型")
    assert res_e_qin == "爆胎"
    assert pri_e == 2

    # 6. 生产车系真正为 HA3H 的秦L，必须准确命中爆胎
    res_ha3h, pri_ha = tagger.evaluate_row("HA3H", "秦L-26款 尊贵型")
    assert res_ha3h == "爆胎"
    assert pri_ha == 2

    # 7. 生产车系真正为 H 的海豹07，必须准确命中爆胎
    res_h, pri_h = tagger.evaluate_row("H", "海豹07换代 尊贵型")
    assert res_h == "爆胎"
    assert pri_h == 2

    # 8. 生产车系为 STHNY（带字母 H），绝不能误匹配为代码 H！
    res_sthny, _ = tagger.evaluate_row("STHNY", "STHNY-15型")
    assert res_sthny != "爆胎"

    # 9. 核心校验点：即使用户数据中车型列包含了规范里的车型名称（如“秦L-26款”），但生产车系是 CKEB，
    # 严格遵循“生产车系与打标型号一一对应，不能出现只检测车型列的情况”，绝不能误打标为爆胎！
    res_ckeb_qin, _ = tagger.evaluate_row("CKEB", "秦L-26款(CKEB-30型-国标充电-79091)")
    assert res_ckeb_qin == "直接式"
    assert res_ckeb_qin != "爆胎"

    # 9. 生产车系为 CKEB，车型包含“宋GT-EV”（带 EV 且带连字符），绝不能误打标为爆胎
    res_ckeb_song, _ = tagger.evaluate_row("CKEB", "宋GT-EV (CKEB-40型)")
    assert res_ckeb_song != "爆胎"


def test_four_photo_requirements(tmp_path):
    """
    针对图片《修改.txt》中提出的四点问题进行完整综合校验：
    1. 国家列表新增新喀里多尼亚、波利尼西亚（法国管辖的海外属地），且触发出口打标
    2. 车型汇总表把所有的单独xlsx数据全部合并到一张表里（sheet 名为‘车型汇总表’），基地放在首列（第一列）
    3. 国家列表表格名修改为地区列表（含中国香港、中国澳门、中国台湾，中国本身受本土保护不误打标出口）
    4. 运行日志与控制台为黑色字体
    """
    import pandas as pd
    from processor.consolidator import DataConsolidator
    from openpyxl import load_workbook

    # ------------------ 校验点 1 & 3: 地区列表与新增属地 ------------------
    region_file = str(tmp_path / "地区列表.xlsx")
    ConfigManager.create_default_country_list(region_file)

    cm = ConfigManager()
    countries = cm.load_country_list(region_file)

    # 1. 验证新增的非主权国家/法国海外属地已包含
    assert "新喀里多尼亚" in countries
    assert "波利尼西亚" in countries
    assert "法属波利尼西亚" in countries

    # 2. 验证表格名为“地区列表”并包含香港、澳门、台湾
    wb_reg = load_workbook(region_file)
    assert "地区列表" in wb_reg.sheetnames
    df_reg = pd.read_excel(region_file, sheet_name="地区列表")
    assert "国家/地区" in df_reg.columns
    assert any("香港" in str(x) for x in df_reg["国家/地区"])
    assert any("澳门" in str(x) for x in df_reg["国家/地区"])
    assert any("台湾" in str(x) for x in df_reg["国家/地区"])
    assert "香港" in countries
    assert "澳门" in countries
    assert "台湾" in countries
    assert "中国" not in countries  # 本土词受保护

    # 3. 验证新喀里多尼亚与波利尼西亚触发出口打标（第一优先级）
    tagger = ModelTagger(cm)
    res_nc, p_nc = tagger.evaluate_row("CKEB", "元PLUS (新喀里多尼亚海外专供版)")
    assert res_nc == "出口" and p_nc == 1

    res_poly, p_poly = tagger.evaluate_row("STEAY", "STEAY-波利尼西亚定制款")
    assert res_poly == "出口" and p_poly == 1

    res_fpoly, p_fpoly = tagger.evaluate_row("UNED", "UNED-法属波利尼西亚版")
    assert res_fpoly == "出口" and p_fpoly == 1

    # ------------------ 校验点 2: 单基地与全基地汇总中“基地放在首列”且“合并到一张表” ------------------
    consolidator = DataConsolidator(tagger)

    # 创建两个基地的模拟月计划文件
    fz_file = str(tmp_path / "★秘密★抚州-月计划 MFZ202637002.xlsx")
    cz_file = str(tmp_path / "★秘密★常州-月计划 MCZ202637003.xlsx")

    df_fz = pd.DataFrame({
        "大车系": ["海鸥", "海鸥"],
        "生产车系": ["STEAY", "STEBU"],
        "车型": ["STEAY尊贵型", "STEBU-波利尼西亚定制款"],
        "9月排产": [100, 200]
    })
    df_fz.to_excel(fz_file, sheet_name="车型汇总", index=False)

    df_cz = pd.DataFrame({
        "大车系": ["汉", "宋"],
        "生产车系": ["CKEB", "UNED"],
        "车型": ["CKEB-新喀里多尼亚专供", "UNED-30型"],
        "9月排产": [300, 400]
    })
    df_cz.to_excel(cz_file, sheet_name="车型汇总", index=False)

    # 2.1 校验单个文件处理后，基地必须在首列（第一列）
    proc_fz, df_proc_fz = consolidator.process_single_base_file(fz_file, output_dir=str(tmp_path / "out"))
    assert df_proc_fz.columns[0] == "基地"
    assert df_proc_fz.loc[0, "基地"] == "抚州"
    assert df_proc_fz.columns[-1] == "配置"

    proc_cz, df_proc_cz = consolidator.process_single_base_file(cz_file, output_dir=str(tmp_path / "out"))
    assert df_proc_cz.columns[0] == "基地"
    assert df_proc_cz.loc[0, "基地"] == "常州"

    # 2.2 校验合并汇总表：全部数据合并到一张表（sheet名为‘车型汇总表’），首列为基地
    summary_path, df_sum = consolidator.consolidate_bases(
        file_paths=[proc_fz, proc_cz],
        output_dir=str(tmp_path / "out"),
        summary_filename="★秘密★全基地车型汇总表.xlsx"
    )
    assert df_sum.columns[0] == "基地"
    assert len(df_sum) == 4
    assert set(df_sum["基地"].unique()) == {"抚州", "常州"}
    assert df_sum.columns[-1] == "配置"

    # 打开 openpyxl 验证汇总工作簿里只有一张表‘车型汇总表’，且首列为基地
    wb_sum = load_workbook(summary_path)
    assert "车型汇总表" in wb_sum.sheetnames
    ws_sum = wb_sum["车型汇总表"]
    assert ws_sum.cell(row=1, column=1).value == "基地"

    # ------------------ 校验点 4: 日志与控制台为黑色字体 ------------------
    import inspect
    import gui
    source = inspect.getsource(gui.TPMSAppGUI._build_bottom_bar)
    assert 'fg="#000000"' in source
    assert 'tag_config("INFO", foreground="#000000"' in source
    assert 'tag_config("SUCCESS", foreground="#000000"' in source
    assert 'tag_config("WARNING", foreground="#000000"' in source
    assert 'tag_config("ERROR", foreground="#000000"' in source


def test_photo_batch2_requirements(tmp_path):
    """
    针对图片第二批修改要求进行全面测试校验：
    1. 乌兹别克斯坦简称修改为乌兹或者乌兹别克，二者均计入出口
    2. 车型一列出现欧标、东南亚、出口、右舵也计入出口，且加入地区列表
    3. 出现国家/地区、常用中文简称、官方全称/别名、所属大洲（中国除外）也计入出口
    4. 系统状态与生产概览中，第三项标为蓝色，一二项为黑色
    5. 控制台字体无锯齿，与上方清单框一致 (Microsoft YaHei UI)
    6. 软件高度修改为 900
    7. 右侧生成测试用例/模板按钮已被删除
    """
    import pandas as pd
    from processor.consolidator import DataConsolidator
    from openpyxl import load_workbook

    # 1. 验证地区列表生成与词条
    region_file = str(tmp_path / "地区列表.xlsx")
    ConfigManager.create_default_country_list(region_file)

    cm = ConfigManager()
    countries = cm.load_country_list(region_file)

    # 验证乌兹与乌兹别克均已加入
    assert "乌兹" in countries
    assert "乌兹别克" in countries
    assert "乌兹别克斯坦" in countries

    # 验证欧标、东南亚、出口、右舵均加入地区列表
    assert "欧标" in countries
    assert "东南亚" in countries
    assert "出口" in countries
    assert "右舵" in countries

    # 验证所属大洲（欧洲、美洲、非洲、大洋洲等）进入出口库，且中国、亚洲、亚太受保护不计入出口
    assert "欧洲" in countries
    assert "美洲" in countries
    assert "大洋洲" in countries
    assert "非洲" in countries
    assert "中国" not in countries
    assert "亚洲" not in countries
    assert "亚太" not in countries

    tagger = ModelTagger(cm)

    # 2. 验证打标：只出现亚洲或者亚太绝不计入出口（满足用户明确需求）
    res_yz, _ = tagger.evaluate_row("UNED", "汉 亚洲版")
    assert res_yz != "出口", f"只出现亚洲不应该算出口，但得到了: {res_yz}"

    res_yt, _ = tagger.evaluate_row("UNED", "汉 亚太尊贵型")
    assert res_yt != "出口", f"只出现亚太不应该算出口，但得到了: {res_yt}"

    res_ckeb_yt, _ = tagger.evaluate_row("CKEB", "海豚 亚太旗舰款")
    assert res_ckeb_yt != "出口"

    # 若同时出现了真正的出口国家或明确出口标识，则依然准确计入出口（第一优先级）
    res_yt_jp, p_yt_jp = tagger.evaluate_row("CKEB", "海豚 亚太日本定制版")
    assert res_yt_jp == "出口" and p_yt_jp == 1

    # 3. 验证打标：乌兹 / 乌兹别克
    res_wz, p_wz = tagger.evaluate_row("CKEB", "秦PLUS (乌兹专供款)")
    assert res_wz == "出口" and p_wz == 1

    res_wzbk, p_wzbk = tagger.evaluate_row("CKEB", "秦PLUS (乌兹别克版)")
    assert res_wzbk == "出口" and p_wzbk == 1

    # 4. 验证打标：欧标、东南亚、出口、右舵
    res_ob, p_ob = tagger.evaluate_row("CKEB", "海豚 欧标高配版")
    assert res_ob == "出口" and p_ob == 1

    res_dny, p_dny = tagger.evaluate_row("UNED", "宋PLUS 东南亚首发旗舰型")
    assert res_dny == "出口" and p_dny == 1

    res_ck, p_ck = tagger.evaluate_row("STEBU", "海鸥 出口型定制款")
    assert res_ck == "出口" and p_ck == 1

    res_yd, p_yd = tagger.evaluate_row("UNHG", "汉EV (右舵版)")
    assert res_yd == "出口" and p_yd == 1

    # 5. 验证打标：所属大洲（如欧洲、非洲、大洋洲）
    res_oz, p_oz = tagger.evaluate_row("CKEB", "海豚 欧洲定制纪念款")
    assert res_oz == "出口" and p_oz == 1

    res_fz, p_fz = tagger.evaluate_row("STEAY", "STEAY-非洲版")
    assert res_fz == "出口" and p_fz == 1

    # 5. 验证静态源码：GUI配置项
    import inspect
    import gui

    src_init = inspect.getsource(gui.TPMSAppGUI.__init__)
    assert '"1180x900"' in src_init or '1120, 900' in src_init

    src_top = inspect.getsource(gui.TPMSAppGUI._build_top_header)
    # 第一项与第二项黑色，第三项蓝色
    assert 'foreground="#000000"' in src_top
    assert 'foreground="#0D47A1"' in src_top
    assert '#263238' not in src_top
    assert '#2E7D32' not in src_top

    src_spec = inspect.getsource(gui.TPMSAppGUI._build_spec_config_frame)
    assert '生成测试用例/模板' not in src_spec

    src_bottom = inspect.getsource(gui.TPMSAppGUI._build_bottom_bar)
    assert 'Consolas' not in src_bottom


def test_bonaire_and_empty_secondary_code_matching(tmp_path):
    """
    测试用户明确指出的两大核心修正需求：
    1. 地区列表新增博奈尔岛（博奈尔/博内尔/博奈尔岛/博内尔岛均准确计入出口）
    2. 车型分类规则中，如果只有一级代码，没有二级代码：
       需要总表中生产车系一列和一级车型代码匹配，则属于该sheet分类（如爆胎），
       且不受车型列具体字符串或车型名称列的影响；同时短代码（如 'E'）绝不会误判跨列包含的代码（如 'CKEB' 或 'UNE'）。
    """
    import pandas as pd
    from processor.config_manager import ConfigManager
    from processor.tagger import ModelTagger

    # 1. 验证地区列表中的博奈尔岛
    region_file = str(tmp_path / "地区列表.xlsx")
    ConfigManager.create_default_country_list(region_file)

    cm = ConfigManager()
    countries = cm.load_country_list(region_file)
    assert "博奈尔岛" in countries
    assert "博奈尔" in countries
    assert "博内尔" in countries

    tagger = ModelTagger(cm)
    res_bne, p_bne = tagger.evaluate_row("CKEB", "海豚 (博奈尔岛专供版)")
    assert res_bne == "出口" and p_bne == 1

    res_bn, p_bn = tagger.evaluate_row("CKEB", "海豚 (博奈尔定制款)")
    assert res_bn == "出口" and p_bn == 1

    res_bon, p_bon = tagger.evaluate_row("CKEB", "海豚 (博内尔版)")
    assert res_bon == "出口" and p_bon == 1

    # 2. 验证“只有一级代码，没有二级代码，总表中生产车系与一级代码匹配即归属该sheet分类（如爆胎）”
    spec_file = str(tmp_path / "测试车型规范.xlsx")
    with pd.ExcelWriter(spec_file, engine="openpyxl") as writer:
        df_baotai = pd.DataFrame({
            "车型名称": ["钛7 改款", "宋GT-EV", "秦L-26款", "秦L-26款", "唐Pro26款", "腾势N8", "海狮06 秋季款", "方程豹-钛6"],
            "一级车型代码": ["QZH-3T", "UFE", "HA3H", "E", "QBH", "SJH", "UGE", "OW"],
            "二级车型代码": ["", "", "", "", "", "", "", ""],
            "备注": ["爆胎", "爆胎", "爆胎", "爆胎", "爆胎", "爆胎", "爆胎", "爆胎"]
        })
        df_baotai.to_excel(writer, sheet_name="爆胎", index=False)

        df_direct = pd.DataFrame({
            "生产车系": ["CKEB", "UNED"],
            "车型": ["海豚", "元PLUS"],
            "一级车型代码": ["CKEB", "UNED"],
            "二级车型代码": ["30", "20"],
        })
        df_direct.to_excel(writer, sheet_name="直接式", index=False)

    cm_spec = ConfigManager(model_spec_path=spec_file, country_list_path=region_file)
    tagger_spec = ModelTagger(cm_spec)

    # 验证单行数据即使车型列文字与规范中的“车型名称”完全不同，只要生产车系与一级车型代码完全匹配，即命中“爆胎”
    assert tagger_spec.evaluate_row("QZH-3T", "钛7 120km 旗舰型")[0] == "爆胎"
    assert tagger_spec.evaluate_row("UFE", "宋GT EV 500km 豪华款")[0] == "爆胎"
    assert tagger_spec.evaluate_row("HA3H", "秦L 120km 卓越型")[0] == "爆胎"
    assert tagger_spec.evaluate_row("E", "秦L 120km 卓越型")[0] == "爆胎"
    assert tagger_spec.evaluate_row("QBH", "唐Pro 卓越版")[0] == "爆胎"
    assert tagger_spec.evaluate_row("SJH", "腾势N8 尊享版")[0] == "爆胎"
    assert tagger_spec.evaluate_row("UGE", "海狮06 舒适型")[0] == "爆胎"
    assert tagger_spec.evaluate_row("OW", "方程豹-钛6 越野型")[0] == "爆胎"

    # 验证全角连字符与括号说明匹配
    assert tagger_spec.evaluate_row("QZH－3T", "钛7 普通版")[0] == "爆胎"
    assert tagger_spec.evaluate_row("HA3H(秦L)", "秦L 卓越版")[0] == "爆胎"

    # 验证严格防短代码误判：CKEB 与 UNE 绝不会因为包含 'E' 而被误打标为爆胎
    res_ckeb, _ = tagger_spec.evaluate_row("CKEB", "海豚 智航版")
    assert res_ckeb != "爆胎"

    res_une, _ = tagger_spec.evaluate_row("UNE", "秦L 卓越型")
    assert res_une != "爆胎"

    # 验证有二级代码的 sheet 仍严格要求二级代码
    assert tagger_spec.evaluate_row("CKEB", "海豚 (CKEB-30型)")[0] == "直接式"
    assert tagger_spec.evaluate_row("UNED", "元PLUS (UNED-20型)")[0] == "直接式"



