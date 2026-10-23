"""测试车型及车型分类三级打标逻辑 (test_tagger.py)

涵盖：
1. 合计/总计/小计行自动剔除测试
2. 优先级 1:
   - “车型”列包含“车型分类规范”中提及的分类 (eg: “EWEK-10型” 或 “EWEK-10”)
   - “生产车系”包含“一级车型代码”，“车型”列包含“二级车型代码”搭配符号文字的组合 (eg: “-10”, “-10型”, “10型”, “-10款”)
   - 排除规则: 只有“10”不计入 sheet 分类
3. 优先级 2:
   - 全世界国家及中文简称匹配 -> 标注“出口” (eg: 沙特、阿联酋、印尼、日本、德国、澳洲等)
4. 优先级 3:
   - 未设计行 -> 留空 ""
"""

import os
import pytest
import pandas as pd
from processor.config_manager import ConfigManager
from processor.tagger import ModelTagger


@pytest.fixture
def sample_config(tmp_path):
    spec_path = str(tmp_path / "车型分类规范.xlsx")
    country_path = str(tmp_path / "国家列表.xlsx")

    ConfigManager.create_default_model_spec(spec_path)
    ConfigManager.create_default_country_list(country_path)

    mgr = ConfigManager(model_spec_path=spec_path, country_list_path=country_path)
    return mgr


@pytest.fixture
def tagger(sample_config):
    return ModelTagger(config_mgr=sample_config)


class TestModelTagger:

    def test_priority_spec_full_model_name(self, tagger):
        """测试车型规范匹配（优先级2）: 车型列包含规范中的分类全称"""
        res, pri = tagger.evaluate_row(prod_series="任意车系", model_name="EWEK-10型")
        assert res == "爆胎"
        assert pri == 2

        res, pri = tagger.evaluate_row(prod_series="", model_name="EWEK-10")
        assert res == "爆胎"
        assert pri == 2

        res, pri = tagger.evaluate_row(prod_series="仰望", model_name="前驱EWEK-20旗舰型")
        assert res == "爆胎"
        assert pri == 2

    def test_priority_spec_code_pair_with_symbols(self, tagger):
        """测试车型规范匹配（优先级2）: 生产车系包含一级代码，车型包含二级代码搭配符号或汉字"""
        # -10
        res, pri = tagger.evaluate_row(prod_series="EWEK", model_name="-10")
        assert res == "爆胎"
        assert pri == 2

        # -10型
        res, pri = tagger.evaluate_row(prod_series="EWEK", model_name="-10型")
        assert res == "爆胎"
        assert pri == 2

        # -10"
        res, pri = tagger.evaluate_row(prod_series="EWEK", model_name='-10"')
        assert res == "爆胎"
        assert pri == 2

        # 10型
        res, pri = tagger.evaluate_row(prod_series="EWEK", model_name="10型")
        assert res == "爆胎"
        assert pri == 2

        # ATTO 与 05
        res, pri = tagger.evaluate_row(prod_series="ATTO", model_name="-05款")
        assert res == "胎压监测"
        assert pri == 2

    def test_priority_spec_exclude_standalone_code(self, tagger):
        """测试规范关键例外: 只有'10'不计入sheet分类"""
        # 生产车系为 EWEK，但车型只有孤立的 "10"
        res, pri = tagger.evaluate_row(prod_series="EWEK", model_name="10")
        assert res != "爆胎"
        assert res == ""
        assert pri == 3

        # 带有前后空格的 " 10 "
        res, pri = tagger.evaluate_row(prod_series="EWEK", model_name=" 10 ")
        assert res != "爆胎"
        assert res == ""
        assert pri == 3

    def test_priority_1_country_export_and_abbreviations(self, tagger):
        """测试第一优先级: 车型出现国家列表中的国家或中文简称，优先标注“出口”"""
        res, pri = tagger.evaluate_row(prod_series="HAN", model_name="汉EV沙特尊贵版")
        assert res == "出口"
        assert pri == 1

        # 阿联酋简称
        res, pri = tagger.evaluate_row(prod_series="QIN", model_name="秦PLUS阿联酋旗舰版")
        assert res == "出口"
        assert pri == 1

        # 印尼简称
        res, pri = tagger.evaluate_row(prod_series="SEAL", model_name="海豹印尼右舵版")
        assert res == "出口"
        assert pri == 1

        # 澳洲简称
        res, pri = tagger.evaluate_row(prod_series="TANG", model_name="唐澳洲版越野款")
        assert res == "出口"
        assert pri == 1

        # 日本
        res, pri = tagger.evaluate_row(prod_series="SEAL", model_name="海豹日本版")
        assert res == "出口"
        assert pri == 1

    def test_priority_country_over_model_spec(self, tagger):
        """测试优先级覆盖: 国家/出口作为第一优先级优先于车型分类规范（沙特优先于爆胎）"""
        # 车型同时包含规范型号（EWEK-10型）与国家（沙特），严格按第一优先级打标为“出口”
        res, pri = tagger.evaluate_row(prod_series="EWEK", model_name="EWEK-10型沙特特别版")
        assert res == "出口"
        assert pri == 1

    def test_priority_3_unmatched_blank(self, tagger):
        """测试优先级3: 未匹配行配置列为空白字符串"""
        res, pri = tagger.evaluate_row(prod_series="D9", model_name="腾势D9尊荣型")
        assert res == ""
        assert pri == 3

        res, pri = tagger.evaluate_row(prod_series="QIN", model_name="秦PLUS冠军版")
        assert res == ""
        assert pri == 3

    def test_filter_total_and_summary_rows(self, tagger):
        """测试自动识别并剔除‘合计’、‘总计’、‘小计’汇总行"""
        df = pd.DataFrame({
            "大车系": ["仰望", "海洋", "王朝", "腾势", "合计", "总计"],
            "生产车系": ["EWEK", "EWEK", "HAN", "D9", "合计", ""],
            "车型": ["EWEK-10型", "10", "沙特版", "尊贵型", "合计", "小计汇总"],
            "排产量": [100, 200, 300, 400, 1000, 1000]
        })
        res_df = tagger.tag_dataframe(df, drop_totals=True)

        # 包含合计、总计/小计的行被剔除，仅保留前4行有效车型
        assert len(res_df) == 4
        assert "合计" not in res_df["车型"].values
        assert "小计汇总" not in res_df["车型"].values
        assert res_df["配置"].tolist() == ["爆胎", "", "出口", ""]

    def test_complex_realworld_model_strings(self, tagger):
        """测试复杂长文本、含括号/换行/前后修饰语的真实工况车型列检测"""
        # 1. 复杂长文本中嵌入 EWEK-10型
        m1 = "BYD7000BEV1 汉EV 605KM 超长续航尊贵型(EWEK-10型) 珠光白\n带高级智能驾驶"
        res, pri = tagger.evaluate_row(prod_series="BYD-HAN", model_name=m1)
        assert res == "爆胎"
        assert pri == 2

        # 2. 生产车系为 EWEK，车型长文本中包含 -10型
        m2 = "汉EV 荣耀版 605KM 旗舰型 -10型 黑色内饰"
        res, pri = tagger.evaluate_row(prod_series="EWEK", model_name=m2)
        assert res == "爆胎"
        assert pri == 2

        # 3. 生产车系为 EWEK，车型长文本中包含 - 10（带空格连字符）
        m3 = "汉EV 荣耀版 605KM 旗舰型 - 10 黑色内饰"
        res, pri = tagger.evaluate_row(prod_series="EWEK", model_name=m3)
        assert res == "爆胎"
        assert pri == 2

        # 4. 生产车系为 EWEK，车型长文本中包含 -10"（双引号）
        m4 = '汉EV 旗舰型 -10" 灰色'
        res, pri = tagger.evaluate_row(prod_series="EWEK", model_name=m4)
        assert res == "爆胎"
        assert pri == 2

        # 5. 生产车系为 EWEK，车型长文本中包含孤立的 10（纯10排除）
        m5 = "汉EV 旗舰型 10 黑色"
        res, pri = tagger.evaluate_row(prod_series="EWEK", model_name=m5)
        assert res == ""
        assert pri == 3

        # 6. 车型长文本中直接显式包含配置名“爆胎”
        m6 = "宋PLUS DM-i 110KM 旗舰型 (配爆胎应急防护系统)"
        res, pri = tagger.evaluate_row(prod_series="SONG", model_name=m6)
        assert res == "爆胎"
        assert pri == 2

        # 7. 复杂长文本中的海外地区关键词（中东/迪拜）
        m7 = "海豹 550KM 纯电轿车 中东迪拜特别版 右舵"
        res, pri = tagger.evaluate_row(prod_series="SEAL", model_name=m7)
        assert res == "出口"
        assert pri == 1

    def test_clean_model_noise(self, tagger):
        """测试车型列清洗：去除 (普通)、(选装激光雷达)、试验、尾随Y等"""
        assert tagger.clean_model_text("STEAY", "STEAY尊贵型Y") == "STEAY尊贵型"
        assert tagger.clean_model_text("STEBU", "STEBU-10型") == "STEBU-10型"
        assert tagger.clean_model_text("STHNY", "STHNY-15型") == "STHNY-15型"
        assert tagger.clean_model_text("UNED", "UNED-30型(普通)") == "UNED-30型"
        assert tagger.clean_model_text("UNEH", "UNEH-30型(选装激光雷达)") == "UNEH-30型"
        assert tagger.clean_model_text("UNHD", "UNHD-10型试验") == "UNHD-10型"
        assert tagger.clean_model_text("UNHG", "UNHG-30型(选装激光雷达)试验") == "UNHG-30型"
        assert tagger.clean_model_text("CKEB", "(CKEB-30型-右舵-日标充电-日本79091)") == "CKEB-30型"
        assert tagger.clean_model_text("EWEK", "汉EV 605KM 尊贵型(EWEK-10型) 黑色") == "EWEK-10型"
        assert tagger.clean_model_text("EWEK", "汉EV 605KM 尊贵型(EWEK-10) 黑色") == "EWEK-10"

    def test_tag_dataframe_preserves_full_model_info_and_handles_merged_cells(self, tagger):
        """测试 tag_dataframe 保留车型列完整信息（如包含选装、规格、型号后缀等），并正确向前填充大车系"""
        df = pd.DataFrame({
            "大车系": ["长沙基地合计", None, "STE(海鸥)", None, "STH(海豚)", None, "UNE", None, None],
            "生产车系": [None, "常规", "合计", "STEAY", "合计", "STHNY", "合计", "UNEC", "UNED"],
            "车型": [None, None, None, "STEAY尊贵型Y", None, "STHNY-15型", None, "UNEC-10型", "UNED-30型(普通)"],
            "计划排产": [1000, 1000, 100, 100, 200, 200, 700, 300, 400]
        })

        res_df = tagger.tag_dataframe(df, drop_totals=True)

        # 验证汇总行已被正确剔除（共 4 行真实车型）
        assert len(res_df) == 4

        # 验证车型列保存完整信息，不破坏原始型号与选装规格
        assert res_df["车型"].tolist() == [
            "STEAY尊贵型Y",
            "STHNY-15型",
            "UNEC-10型",
            "UNED-30型(普通)"
        ]

        # 验证大车系没有被首行的合计删空，正确继承了各自分组
        assert res_df["大车系"].tolist() == [
            "STE(海鸥)",
            "STH(海豚)",
            "UNE",
            "UNE"
        ]

    def test_single_primary_code_without_secondary_code_not_polluted_by_ffill(self, tmp_path):
        """测试无二级代码的一级车型（如 SNED），绝不被上一行二级代码（如 EWEL 20）向下填充污染，且全型号均打标命中"""
        test_excel = tmp_path / "spec.xlsx"
        with pd.ExcelWriter(str(test_excel)) as writer:
            df_bt = pd.DataFrame({
                "车型名称": ["仰望U8", "腾势N8L", "汉EV"],
                "一级车型代码": ["EWEL", "SNED", "EUEH"],
                "二级车型代码": ["20", None, "10"]
            })
            df_bt.to_excel(writer, sheet_name="爆胎", index=False)

            df_zj = pd.DataFrame({
                "车型名称": ["海豚"],
                "一级车型代码": ["CKEB"],
                "二级车型代码": ["30"]
            })
            df_zj.to_excel(writer, sheet_name="直接式", index=False)

        cm = ConfigManager()
        cm.load_model_spec(str(test_excel))

        # 验证 SNED 的二级代码绝不能被上一行的 20 污染
        sned_rules = [r for r in cm.sheet_rules["爆胎"]["model_rules"] if r["c1"] == "SNED"]
        assert len(sned_rules) == 1
        assert sned_rules[0]["c2"] == ""
        assert "SNED" in cm.sheet_rules["爆胎"]["empty_code_primaries"]

        tagger = ModelTagger(cm)
        # 测试 SNED-10 与 SNED-20 无论有无生产车系，均能且仅能打标为爆胎
        assert tagger.evaluate_row("SNED", "(SNED-10型)")[0] == "爆胎"
        assert tagger.evaluate_row("SNED", "(SNED-10型选装电动折叠暗夜灰车顶行李架及单排双座车体内后视镜)")[0] == "爆胎"
        assert tagger.evaluate_row("SNED", "(SNED-20型)")[0] == "爆胎"
        assert tagger.evaluate_row("SNED", "(SNED-20型选装安全低风阻组合金车轮)")[0] == "爆胎"
        assert tagger.evaluate_row("", "(SNED-10型)")[0] == "爆胎"
        assert tagger.evaluate_row("", "(SNED-20型)")[0] == "爆胎"

    def test_parenthesized_secondary_code_matching(self, tmp_path):
        """测试二级代码被括号包裹的复合格式（如 ST2EB(30)型、(ST2EB(30)型选装...)）能正确打标"""
        test_excel = tmp_path / "spec_st2eb.xlsx"
        with pd.ExcelWriter(str(test_excel)) as writer:
            df_bt = pd.DataFrame({
                "车型名称": ["腾势Z9"],
                "一级车型代码": ["ST2EB"],
                "二级车型代码": ["30"]
            })
            df_bt.to_excel(writer, sheet_name="爆胎", index=False)

        cm = ConfigManager()
        cm.load_model_spec(str(test_excel))
        tagger = ModelTagger(cm)

        complex_m = "(ST2EB(30)型选装二排航空座椅+8678主机+AR-HUD+12.3寸副驾屏+27扬+4门软包)"
        standard_m = "(ST2EB(30型)86593)"

        # 验证有生产车系时
        assert tagger.evaluate_row("ST2EB", complex_m)[0] == "爆胎"
        assert tagger.evaluate_row("ST2EB", standard_m)[0] == "爆胎"

        # 验证生产车系为空时（从车型列复合模式命中）
        assert tagger.evaluate_row("", complex_m)[0] == "爆胎"
        assert tagger.evaluate_row("", standard_m)[0] == "爆胎"

    def test_three_level_hierarchy_rules(self, tmp_path):
        """测试三级规范体系：1级大车系筛选代码、2级生产车系筛选代码、3级车型筛选代码"""
        test_excel = tmp_path / "spec_three_level.xlsx"
        with pd.ExcelWriter(str(test_excel)) as writer:
            df_bt = pd.DataFrame({
                "车型名称": ["秦MAX-底盘", "秦MAX-底盘", "海狮08", "大汉-底盘", "大汉-底盘"],
                "一级大车系筛选代码": ["", "", "SYH", "HSH", "HSE"],
                "二级生产车系筛选代码": ["EWEK", "EWEK", "", "", ""],
                "三级车型筛选代码": ["10", "20", "", "", ""]
            })
            df_bt.to_excel(writer, sheet_name="爆胎", index=False)

        cm = ConfigManager()
        rules = cm.load_model_spec(str(test_excel))

        # 验证规则解析
        bt_rule = rules["爆胎"]
        assert "SYH" in bt_rule["major_series_rules"]
        assert "HSH" in bt_rule["major_series_rules"]
        assert "HSE" in bt_rule["major_series_rules"]
        assert len(bt_rule["major_series_rules"]) == 3

        pairs = [p for p in bt_rule["code_pairs"] if p[0] == "EWEK"]
        c2s = {p[1] for p in pairs}
        assert "10" in c2s and "20" in c2s

        tagger = ModelTagger(cm)

        # 1. 验证 1级大车系筛选：大车系匹配 SYH / HSH / HSE 直接打标爆胎
        assert tagger.evaluate_row(prod_series="SYH", model_name="海狮08 豪华型", series_a="SYH")[0] == "爆胎"
        assert tagger.evaluate_row(prod_series="", model_name="海狮08 豪华型", series_a="SYH")[0] == "爆胎"
        assert tagger.evaluate_row(prod_series="HSH-P1", model_name="大汉-底盘", series_a="HSH")[0] == "爆胎"
        assert tagger.evaluate_row(prod_series="HSE", model_name="大汉", series_a="海狮08 (SYH)")[0] == "爆胎"

        # 2. 验证非规则中大车系不命中爆胎
        assert tagger.evaluate_row(prod_series="QZE", model_name="钛7-电器", series_a="QZE")[0] != "爆胎"

        # 3. 验证 2+3级代码组合：EWEK-10 与 EWEK-20 打标爆胎，EWEK-30 不打标爆胎
        assert tagger.evaluate_row(prod_series="EWEK", model_name="秦MAX-底盘(EWEK-10型)", series_a="秦MAX")[0] == "爆胎"
        assert tagger.evaluate_row(prod_series="EWEK", model_name="秦MAX-底盘(EWEK-20型)", series_a="秦MAX")[0] == "爆胎"
        assert tagger.evaluate_row(prod_series="EWEK", model_name="秦MAX-底盘(EWEK-30型)", series_a="秦MAX")[0] != "爆胎"

        # 4. 验证 tag_dataframe 全流程
        df_prod = pd.DataFrame({
            "大车系": ["SYH", "HSH", "秦MAX", "秦MAX", "未知车系"],
            "生产车系": ["SYH", "HSH-1", "EWEK", "EWEK", "OTHER"],
            "车型": ["海狮08", "大汉-底盘", "秦MAX-底盘(EWEK-10型)", "秦MAX-底盘(EWEK-30型)", "普通测试车"]
        })
        tagged_df = tagger.tag_dataframe(df_prod, drop_totals=False)
        assert tagged_df.at[0, "配置"] == "爆胎"  # SYH 大车系命中
        assert tagged_df.at[1, "配置"] == "爆胎"  # HSH 大车系命中
        assert tagged_df.at[2, "配置"] == "爆胎"  # EWEK-10 命中
        assert tagged_df.at[3, "配置"] != "爆胎"  # EWEK-30 未配置
        assert tagged_df.at[4, "配置"] != "爆胎"

    def test_backward_compatibility_old_two_level_spec(self, tmp_path):
        """测试向下兼容历史旧表头：'一级车型代码' 与 '二级车型代码' 自动映射为 2级生产车系 与 3级车型代码"""
        test_excel = tmp_path / "spec_old_two_level.xlsx"
        with pd.ExcelWriter(str(test_excel)) as writer:
            df_old = pd.DataFrame({
                "车型名称": ["汉EV", "汉EV", "海豹"],
                "一级车型代码": ["EWEK", "EWEK", "SNED"],
                "二级车型代码": ["10", "20", ""]
            })
            df_old.to_excel(writer, sheet_name="爆胎", index=False)

        cm = ConfigManager()
        rules = cm.load_model_spec(str(test_excel))
        bt = rules["爆胎"]

        # 验证 EWEK-10 与 EWEK-20 映射进 code_pairs
        assert ("EWEK", "10") in bt["code_pairs"]
        assert ("EWEK", "20") in bt["code_pairs"]
        # 验证 SNED 映射进 empty_code_primaries
        assert "SNED" in bt["empty_code_primaries"]
        # 验证旧表无 1级大车系筛选
        assert len(bt["major_series_rules"]) == 0

        tagger = ModelTagger(cm)
        assert tagger.evaluate_row("EWEK", "(EWEK-10型)")[0] == "爆胎"
        assert tagger.evaluate_row("SNED", "(SNED 尊贵型)")[0] == "爆胎"

    def test_exact_headers_from_user_photo(self, tmp_path):
        """测试用户现场照片1:1真实表头（车型名称、一级大车系筛选代码、二级生产车系筛选代码、三级车型筛选代码）"""
        test_excel = tmp_path / "user_photo_spec.xlsx"
        df_photo = pd.DataFrame({
            "车型名称": [
                "秦MAX-底盘", "秦MAX-底盘",
                "海狮08", "大汉-底盘", "大汉-底盘", "钛7-电器",
                "海豹08", "海豹08", "海豹07换代", "海豹07换代"
            ],
            "一级大车系筛选代码": [
                None, None,
                "SYH", "HSH", "HSE", "QZE",
                "HYE", "HYH", "HX2E", "HX2H"
            ],
            "二级生产车系筛选代码": [
                "EWEK", "EWEK",
                None, None, None, None,
                None, None, None, None
            ],
            "三级车型筛选代码": [
                "10", "20",
                None, None, None, None,
                None, None, None, None
            ]
        })
        with pd.ExcelWriter(str(test_excel)) as writer:
            df_photo.to_excel(writer, sheet_name="爆胎", index=False)

        cm = ConfigManager()
        rules = cm.load_model_spec(str(test_excel))
        bt = rules["爆胎"]

        # 验证 1级大车系 8 个
        assert bt["major_series_rules"] == {"SYH", "HSH", "HSE", "QZE", "HYE", "HYH", "HX2E", "HX2H"}
        # 验证 2+3级组合 2 组 (EWEK-10, EWEK-20)
        assert ("EWEK", "10") in bt["code_pairs"]
        assert ("EWEK", "20") in bt["code_pairs"]

        tagger = ModelTagger(cm)

        # 1. 验证规范表结构直接打标：全部10行均能打标“爆胎”且不被误删
        tagged_spec = tagger.tag_dataframe(df_photo, drop_totals=False)
        assert len(tagged_spec) == 10
        assert all(t == "爆胎" for t in tagged_spec["配置"])

        # 2. 验证实际月计划排产表打标
        df_plan = pd.DataFrame({
            "大车系": ["海狮08", "大汉", "大汉-底盘", "钛7", "海豹08", "海豹07换代", "秦MAX", "秦MAX"],
            "生产车系": ["SYH", "HSH", "HSE", "QZE", "HYE", "HX2E", "EWEK", "EWEK"],
            "车型": [
                "SYH-10型",
                "HSH-10型",
                "HSE-20型",
                "钛7 旗舰型",
                "HYE-01型",
                "HX2E-01型",
                "EWEK-10型",
                "EWEK-30型"
            ],
            "排产": [100, 200, 300, 400, 500, 600, 700, 800]
        })
        tagged_plan = tagger.tag_dataframe(df_plan, drop_totals=True)
        assert len(tagged_plan) == 8
        assert tagged_plan["配置"].tolist() == [
            "爆胎",  # 海狮08 (SYH)
            "爆胎",  # 大汉 (HSH)
            "爆胎",  # 大汉-底盘 (HSE)
            "爆胎",  # 钛7 (QZE)
            "爆胎",  # 海豹08 (HYE)
            "爆胎",  # 海豹07换代 (HX2E)
            "爆胎",  # EWEK-10
            ""      # EWEK-30 未配置
        ]




