"""打标与分类匹配引擎 (ModelTagger)

在复杂长文本车型列中精准检测目标文字与特征，支持：
1. 复杂长文本智能清洗与标准化（全角转半角、标点规整、换行符清洗、多余空白压缩）
2. 自动剔除“合计/总计/小计/汇总”汇总行及全空无效行
3. 提取车型列中的核心代码与显示文字（参考前版本正则与模式抽取）
4. 优先级 1（出口国家及地区划分）：
   - 全世界 197+ 国家名称及其常用中文简称（沙特、阿联酋、印尼、澳洲、日本、德国等）
   - 包含中东、东盟、欧盟、欧洲、非洲、北美、拉美、迪拜及出口/海外/右舵等关键标识
5. 优先级 2（车型分类规范匹配与长文本局部文字提取）：
   - 检测车型/车系中直接包含规范配置标签（如“爆胎”、“独立控制器”、“间接式”、“直接式”、“直通”等直接配置词）
   - 检测车型中包含规范中提及的分类全称（如“EWEK-10型”、“EWEK-10”，兼容前后文字、括号及空格）
   - 规范中二级车型代码为空时，该一级车型代码全部归入该 Sheet 分类
   - 生产车系含一级代码，车型列包含二级代码搭配符号文字组合（如“-10”、“-10型”、“-10\"”、“10型”等），严格排除纯孤立数字“10”
6. 优先级 3（默认规则）：未设计的行配置列留空
"""

import re
from typing import Optional, Dict, Any, List, Tuple, Set
import pandas as pd
from .config_manager import ConfigManager


class ModelTagger:
    """车型分类打标器（强化长文本部分文字检测与模式匹配）"""

    # 汇总合计关键词
    TOTAL_KEYWORDS = ("合计", "总计", "小计", "汇总", "total", "sum")

    # 全局出口/海外及地区关键词库（包含用户指定：欧标、东南亚、出口、右舵等；排除亚洲与亚太）
    REGION_EXPORT_KEYWORDS = [
        "出口", "右舵", "欧标", "东南亚", "海外", "外销", "外贸", "国际版", "全球版",
        "中东", "东盟", "欧盟", "欧洲", "非洲", "北美", "南美", "拉美", "迪拜",
        "美洲", "大洋洲", "澳洲"
    ]

    # 用户参考全局出口国家及简称库
    FOREIGN_COUNTRY_KEYWORDS = [
        # --- ASIA ---
        '沙特', '阿拉伯', '卡塔尔', '阿联酋', '迪拜', '科威特', '伊拉克', '伊朗', '以色列', '约旦', 
        '黎巴嫩', '叙利亚', '阿曼', '也门', '巴林', '土耳其', '日本', '韩国', '朝鲜', '蒙古', 
        '印度', '巴基斯坦', '孟加拉', '斯里兰卡', '尼泊尔', '不丹', '马尔代夫', 
        '越南', '泰国', '缅甸', '老挝', '柬埔寨', '马来西亚', '新加坡', '印尼', '印度尼西亚', 
        '文莱', '菲律宾', '东帝汶', '哈萨克', '吉尔吉斯', '塔吉克', '乌兹', '乌兹别克', '乌兹别克斯坦', '土库曼', 
        '阿富汗', '格鲁吉亚', '亚美尼亚', '阿塞拜疆', '塞浦路斯', '中东', '东盟', '东南亚', '欧标', '台湾', '中国台湾', '香港', '澳门',
        # --- EUROPE ---
        '俄罗斯', '乌克兰', '白俄罗斯', '英国', '爱尔兰', '法国', '德国', '荷兰', '比利时', '卢森堡', 
        '奥地利', '瑞士', '波兰', '捷克', '斯洛伐克', '匈牙利', '罗马尼亚', '保加利亚', 
        '塞尔维亚', '克罗地亚', '斯洛文尼亚', '波黑', '黑山', '马其顿', '希腊', '阿尔巴尼亚', 
        '意大利', '西班牙', '葡萄牙', '安道尔', '马耳他', '瑞典', '挪威', '芬兰', '丹麦', '冰岛', 
        '爱沙尼亚', '拉脱维亚', '立陶宛', '摩尔多瓦', '圣马力诺', '摩纳哥', '列支敦士登', '梵蒂冈', '科索沃', '欧盟', '欧洲',
        # --- AFRICA ---
        '埃及', '利比亚', '突尼斯', '阿尔及利亚', '摩洛哥', '苏丹', '南苏丹', '埃塞俄比亚', 
        '肯尼亚', '坦桑尼亚', '乌干达', '卢旺达', '布隆迪', '索马里', '吉布提', '厄立特里亚',
        '尼日利亚', '加纳', '科特迪瓦', '塞内加尔', '马里', '几内亚', '利比里亚', '塞拉利昂',
        '刚果', '喀麦隆', '加蓬', '安哥拉', '赞比亚', '津巴布韦', '莫桑比克', '马达加斯加', 
        '南非', '纳米比亚', '博茨瓦纳', '毛里求斯', '塞舌尔', '布基纳法索', '佛得角', '冈比亚', 
        '几内亚比绍', '科摩罗', '圣普', '圣多美', '西撒哈拉', '索马里兰', '乍得', '贝宁', 
        '多哥', '中非', '马拉维', '莱索托', '斯威士兰', '埃斯瓦蒂尼', '赤道几内亚', '毛里塔尼亚', '非洲',
        # --- AMERICAS ---
        '美国', '加拿大', '墨西哥', '北美', '巴西', '阿根廷', '智利', '秘鲁', '哥伦比亚', 
        '委内瑞拉', '厄瓜多尔', '玻利维亚', '巴拉圭', '乌拉圭', '古巴', '牙买加', 
        '海地', '多米尼加', '多米尼克', '巴拿马', '哥斯达黎加', '洪都拉斯', '萨尔瓦多', '危地马拉', 
        '尼加拉瓜', '巴哈马', '巴巴多斯', '特多', '特立尼达', '安巴', '安提瓜', '格林纳达', 
        '圣基茨', '圣卢西亚', '圣文森特', '圭亚那', '苏里南', '伯利兹', '波多黎各', '格陵兰', 
        '百慕大', '开曼', '库拉索', '阿鲁巴', '博奈尔', '博奈尔岛', '博内尔', '博内尔岛', '南美', '拉美',
        # --- OCEANIA ---
        '澳大利亚', '澳洲', '新西兰', '纽西兰', '斐济', '巴布亚新几内亚', '巴新', '萨摩亚', 
        '所罗门', '瓦努阿图', '密克', '基里巴斯', '帕劳', '汤加', '图瓦卢', '瑙鲁', '马绍尔', 
        '库克', '纽埃', '关岛', '新喀里多尼亚', '波利尼西亚', '法属波利尼西亚'
    ]

    # 有效配置分类标签库
    VALID_C_TAGS = ["爆胎", "出口", "独立控制器", "间接式", "直接式"]

    # 行业直接配置通用标签库（按特异性与优先级排序）
    STANDARD_DIRECT_TAGS = ["独立控制器", "直接式", "间接式", "直通", "爆胎"]

    def __init__(self, config_mgr: Optional[ConfigManager] = None):
        self.config_mgr = config_mgr or ConfigManager()

    def set_config(self, config_mgr: ConfigManager):
        self.config_mgr = config_mgr

    @classmethod
    def is_summary_or_total_row(cls, row: pd.Series, model_col: Optional[str] = None) -> bool:
        """判断是否为‘合计’、‘总计’、‘小计’汇总行或无效行"""
        if model_col and model_col in row.index:
            val = row[model_col]
            if pd.isna(val) or not str(val).strip() or str(val).strip().lower() == "nan":
                return True
            val_str = str(val).strip()
            for kw in cls.TOTAL_KEYWORDS:
                if kw in val_str or kw.lower() in val_str.lower():
                    return True

        for c in ["车型", "生产车系", "大车系", "车系", "车系分类"]:
            if c in row.index:
                val_str = str(row[c]).strip()
                for kw in cls.TOTAL_KEYWORDS:
                    if kw in val_str or kw.lower() in val_str.lower():
                        return True

        return False

    @staticmethod
    def normalize_text(text: Any) -> str:
        """
        标准化文本，解决实际复杂 Excel 中的全角字符、换行与空格问题：
        1. 全角破折号与连字符（－、―、—、–）转为标准半角 '-'
        2. 全角及中文引号（“、”、’、‘）转为半角 '"' 与 '\''
        3. 全角括号（（、））转为半角 '(' 与 ')'
        4. 换行符（\\r\\n, \\n）替换为空格
        5. 压缩多个连续空白字符
        """
        if pd.isna(text):
            return ""
        s = str(text)
        # 统一横杠符号
        s = re.sub(r'[\uff0d\u2010\u2012\u2013\u2014\u2015\u2500\u2011]', '-', s)
        # 统一双引号
        s = re.sub(r'[\u201c\u201d\u301d\u301e]', '"', s)
        # 统一单引号
        s = re.sub(r'[\u2018\u2019]', "'", s)
        # 统一圆括号
        s = s.replace('（', '(').replace('）', ')')
        # 统一中括号
        s = s.replace('【', '[').replace('】', ']')
        # 换行与制表符清洗
        s = re.sub(r'[\r\n\t]+', ' ', s)
        # 压缩多余空格
        s = re.sub(r'\s+', ' ', s)
        return s.strip()

    @classmethod
    def clean_model_text(cls, raw_prod: str, raw_model: str) -> str:
        """
        清洗车型列中的噪声文字（如 (普通)、(选装激光雷达)、试验、尾随字母/数字等），
        提取并同步修改车型列为真实有效的核心车型名称。
        
        测试样例与效果：
        - STEAY + STEAY尊贵型Y -> STEAY尊贵型
        - UNED + UNED-30型(普通) -> UNED-30型
        - UNEH + UNEH-30型(选装激光雷达) -> UNEH-30型
        - UNHD + UNHD-10型试验 -> UNHD-10型
        - UNHG + UNHG-30型(选装激光雷达)试验 -> UNHG-30型
        - CKEB + (CKEB-30型-右舵-日标充电-日本79091) -> CKEB-30型
        - EWEK + 汉EV 605KM 尊贵型(EWEK-10型) 黑色 -> EWEK-10型
        - EWEK + 汉EV 605KM 尊贵型(EWEK-10) 黑色 -> EWEK-10
        """
        if not raw_model:
            return str(raw_prod or "").strip()

        prod_clean = str(raw_prod or "").strip()
        model_clean = cls.normalize_text(raw_model)

        if not prod_clean:
            # 没有生产车系，尝试从车型自身提取
            m_xing = re.search(r'[a-zA-Z0-9\u4e00-\u9fa5\-]+型', model_clean)
            if m_xing:
                return m_xing.group(0).strip()
            return model_clean

        esc_p = re.escape(prod_clean)

        # 1. 检查括号内的显式型号定义（如 '(EWEK-10型)' 或 '(CKEB-30型-右舵...)'）
        m_paren = re.search(r'\(([^)]+)\)', model_clean)
        if m_paren:
            paren_content = m_paren.group(1).strip()
            if prod_clean.upper() in paren_content.upper():
                m_p_xing = re.search(esc_p + r'[-_/\s\(\[（【]*[A-Za-z0-9\u4e00-\u9fa5\)\（\]】\-]*?型', paren_content, re.IGNORECASE)
                if m_p_xing:
                    return m_p_xing.group(0).strip()
                m_p_num = re.search(esc_p + r'[-_/\s\(\[（【]*\d+["\']?[\)\]）】]?', paren_content, re.IGNORECASE)
                if m_p_num:
                    return m_p_num.group(0).strip()

        # 2. 生产车系在车型长文本中
        col4_in_col5 = prod_clean.upper() in model_clean.upper()
        has_xing = "型" in model_clean

        if col4_in_col5:
            # 模式 2A: 包含“型”，匹配从生产车系到“型”结束（精准剔除 试验、(选装激光雷达)、尾随Y等）
            if has_xing:
                m1 = re.search(esc_p + r'[-_/\s\(\[（【]*[A-Za-z0-9\u4e00-\u9fa5\)\（\]】\-]*?型', model_clean, re.IGNORECASE)
                if m1:
                    return m1.group(0).strip()

            # 模式 2B: 不含“型”，匹配生产车系后紧跟横杠数字或括号数字 (eg: STEBU-10, EWEK-10, ST2EB(30))
            m2 = re.search(esc_p + r'[-_/\s\(\[（【]*\d+["\']?[\)\]）】]?', model_clean, re.IGNORECASE)
            if m2:
                return m2.group(0).strip()

        # 3. 生产车系不在车型文本中（或车型中未带前缀），但车型中有其他“型”
        if m_paren:
            m_inner = re.search(r'[a-zA-Z0-9\u4e00-\u9fa5\-]+型', m_paren.group(1))
            if m_inner:
                return m_inner.group(0).strip()

        if has_xing:
            m3 = re.search(r'[a-zA-Z0-9\u4e00-\u9fa5\-]+型', model_clean)
            if m3:
                return m3.group(0).strip()

        # 4. 回退处理：剔除结尾括号备注与“试验”标识
        cleaned_fallback = re.sub(r'\s*\([^)]*(?:选装|普通|激光雷达|试验)[^)]*\)\s*', '', model_clean)
        cleaned_fallback = re.sub(r'试验$', '', cleaned_fallback).strip()
        return cleaned_fallback if cleaned_fallback else model_clean

    @classmethod
    def extract_display_text(cls, raw_prod: str, raw_model: str) -> str:
        """从车型长文本中提取代表核心车型型号的显示文字（与 clean_model_text 保持一致）"""
        return cls.clean_model_text(raw_prod, raw_model)

    @classmethod
    def extract_candidate_model_codes(cls, raw_prod: str, raw_model: str, display_text: str) -> Set[str]:
        """提取车型文本中所有候选子型号、括号内代码及分词片段"""
        candidates: Set[str] = set()
        if display_text:
            candidates.add(display_text)
        if raw_prod:
            candidates.add(raw_prod)

        # 提取括号内的所有内容
        for p in re.findall(r'\(([^)]+)\)', raw_model):
            clean_p = p.strip()
            candidates.add(clean_p)
            for seg in re.split(r'[-_/\s]+', clean_p):
                seg_clean = seg.strip()
                if seg_clean and len(seg_clean) >= 2:
                    candidates.add(seg_clean)

        # 提取形如 EWEK-10, CKEB-30型, SEAL-08, ST2EB(30)型 等标准型号
        for code in re.findall(r'[A-Za-z0-9]{2,}[-_/\s\(\[（【]*\d+(?:[\)\]）】]?["\'型款版]*)', raw_model):
            candidates.add(code.strip())

        return candidates

    def matches_secondary_code(
        self,
        model_str: str,
        secondary_code: str,
        primary_code: str = "",
        display_text: str = ""
    ) -> bool:
        """
        在长文本及 display_text 中检测“二级车型代码”是否搭配符号或文字的组合。
        规则明确规定：
        - 包含二级代码搭配符号文字组合，eg: “-10”, “-10型”, “10型”, “-10\"”, “EWEK-10”, “ST2EB(30)型”
        - 只有孤立的“10”不计入 sheet 分类。
        - 兼容前导零（如规范中为 5 时能匹配 05、-05、05型、5型）。
        """
        if not model_str or not secondary_code:
            return False

        sec = str(secondary_code).strip()
        # 兼容整型浮点数 (如 '10.0' -> '10')
        if re.match(r'^\d+\.0$', sec):
            sec = sec[:-2]

        sec_variants = [sec]
        if sec.isdigit():
            val_int = int(sec)
            sec_variants.append(str(val_int))
            sec_variants.append(f"{val_int:02d}")
        # 去重保持顺序
        sec_variants = list(dict.fromkeys(sec_variants))

        # 明确规范排除规则: 只有孤立的“10”不计入 sheet 分类
        if model_str.strip() in sec_variants:
            return False
        if display_text and display_text.strip() in sec_variants:
            return False

        for v in sec_variants:
            escaped_v = re.escape(v)

            # 模式 A: 符号紧贴代码前，前后有数字边界防串号 (eg: -10, _10, /10, - 10, -10型, -10", -10款)
            pattern_prefix = rf'(?<!\d)[-_/#\\~]\s*{escaped_v}(?:["\'型款版\w]*)'
            if re.search(pattern_prefix, model_str, re.IGNORECASE):
                return True

            # 模式 B: 代码紧贴符号或文字后，前无数字 (eg: 10型, 10款, 10版, 10", 10', (10)型, 10)型, 10）型)
            pattern_suffix = rf'(?<!\d){escaped_v}\s*[\)\]）】]?\s*["\'型款版]'
            if re.search(pattern_suffix, model_str, re.IGNORECASE):
                return True

            # 模式 C: 一级代码与二级代码在车型长文本或 display_text 中组合出现
            # (eg: EWEK-10, EWEK_10, EWEK 10型, CKEB-30, ST2EB(30), ST2EB(30)型, ST2EB(30型))
            if primary_code:
                escaped_prim = re.escape(primary_code)
                pattern_combo = rf'{escaped_prim}\s*[-_/\(\[（【]?\s*{escaped_v}(?:[\)\]）】"\'型款版\w]*)'
                if re.search(pattern_combo, model_str, re.IGNORECASE) or (
                    display_text and re.search(pattern_combo, display_text, re.IGNORECASE)
                ):
                    return True

            # 模式 D: 在从车型提取的 display_text 中直接匹配搭配符号/文字 (eg: display_text 为 'CKEB-30型'，v 为 '30')
            if display_text and display_text.strip() not in sec_variants:
                pattern_d = rf'(?<!\d)[-_/#\\~]\s*{escaped_v}|(?<!\d){escaped_v}\s*[\)\]）】]?\s*["\'型款版]'
                if re.search(pattern_d, display_text, re.IGNORECASE):
                    return True

            # 模式 E: 当一级代码已知且生产车系匹配时，二级代码被括号包裹 (eg: ST2EB(30), (30))
            if primary_code:
                pattern_paren = rf'(?<!\d)[\(\[（【]\s*{escaped_v}\s*[\)\]）】]'
                if re.search(pattern_paren, model_str, re.IGNORECASE):
                    return True

        return False

    @classmethod
    def _normalize_code_tokens(cls, text: Any) -> Tuple[str, Set[str]]:
        if pd.isna(text):
            return "", set()
        s = str(text).strip()
        if not s or s.lower() in ["nan", "none"]:
            return "", set()
        if re.match(r'^\d+\.0$', s):
            s = s[:-2]
        # 统一全角半角连字符与破折号
        s = s.replace('－', '-').replace('—', '-').replace('–', '-')
        # 剥离括号备注
        s_no_paren = re.sub(r'\(.*?\)|（.*?）', '', s).strip()
        base_s = s_no_paren if s_no_paren else s

        full_norm = re.sub(r'[\s\(\)（）_\[\]【】/\\.:：]+', '', base_s).upper()
        tokens = set()
        if full_norm:
            tokens.add(full_norm)
        for part in re.split(r'[/,、;\s\+]+', base_s):
            part_norm = re.sub(r'[\s\(\)（）_\[\]【】/\\.:：]+', '', part).upper()
            if part_norm:
                tokens.add(part_norm)
        # 兼容括号内或带有连字符的代码（如 "海狮08 (SYH)" 或 "SYH-底盘"）
        for part in re.split(r'[/,、;\s\+\(\)（）_\-]+', s):
            part_norm = re.sub(r'[\s\(\)（）_\[\]【】/\\.:：]+', '', part).upper()
            if part_norm:
                tokens.add(part_norm)
        return full_norm, tokens

    @classmethod
    def is_prod_series_match(cls, prod_series: Any, c1: Any) -> bool:
        """
        判断总表中的“生产车系”或“大车系”与规范中的代码是否完全匹配。
        用户明确要求：
        1. 必须是总表中生产车系/大车系一列和规范代码完全对应匹配！
        2. 代码必须一一对应完全匹配，绝不允许以短子串方式模糊匹配（例如 c1='E' 绝不能匹配 'CKEB' 或 'UNE'）。
        3. 支持多代码分隔（如 'HA3H, E' 或 'HA3H/E'）、全角连字符 '－' 及括号说明备注自动剔除。
        """
        p_norm, p_tokens = cls._normalize_code_tokens(prod_series)
        c_norm, c_tokens = cls._normalize_code_tokens(c1)
        if not p_tokens or not c_tokens:
            return False
        if p_norm == c_norm:
            return True
        return bool(p_tokens & c_tokens)

    def evaluate_row(
        self,
        prod_series: Any,
        model_name: Any,
        series_a: Any = None,
        c2_code: Any = None
    ) -> Tuple[str, int]:
        """
        对单行长文本数据进行三级打标评估。

        参数:
            prod_series: 生产车系名称 (string/any，例如 CKEB 或 EWEK)
            model_name: 车型名称 (string/any，例如 "(CKEB-30型-右舵-日标充电-日本79091)")
            series_a: 车系分类/大车系 (string/any，例如 CKE 或 汉，或 SYH)
            c2_code: 三级车型筛选代码 (string/any，例如 10 或 20，可选)

        返回:
            (配置标记结果, 命中优先级级别 1|2|3)
        """
        norm_prod = self.normalize_text(prod_series)
        norm_model = self.normalize_text(model_name)
        norm_series_a = self.normalize_text(series_a)
        norm_c2 = ""
        if c2_code is not None and pd.notna(c2_code):
            v_c2 = str(c2_code).strip()
            if re.match(r'^\d+\.0$', v_c2):
                v_c2 = v_c2[:-2]
            if v_c2.lower() not in ["nan", "none"]:
                norm_c2 = v_c2

        if not norm_model and not norm_prod and not norm_series_a and not norm_c2:
            return "", 3

        # 提炼车型中的核心代码与显示文字 (display_text)
        display_text = self.extract_display_text(norm_prod, norm_model)
        candidate_codes = self.extract_candidate_model_codes(norm_prod, norm_model, display_text)

        # ------------------ 优先级 1（国家及地区划分 / 出口匹配） ------------------
        # 用户明确要求：国家作为第一优先级，优先于爆胎等车型规范打标！
        EXCLUDED_EXPORT_TERMS = {"亚洲", "亚太", "中国", "国内", "中国大陆", "中国内地", "中华人民共和国"}

        # 条件 1A: 车型长文本中出现地区或出口标识（出口、海外、中东、迪拜、东盟、欧洲、右舵、欧标、东南亚等）
        for reg in self.REGION_EXPORT_KEYWORDS:
            if reg not in EXCLUDED_EXPORT_TERMS and (reg in norm_model or reg in norm_prod):
                return "出口", 1

        # 条件 1B: 车型长文本或生产车系中出现国家参考库中提及的国家全称或中文简称
        for country in self.config_mgr.countries:
            if country and country not in EXCLUDED_EXPORT_TERMS and (country in norm_model or country in norm_prod):
                return "出口", 1

        # 条件 1C: 匹配用户提供全局海外国家/简称列表
        for country in self.FOREIGN_COUNTRY_KEYWORDS:
            if country and country not in EXCLUDED_EXPORT_TERMS and (country in norm_model or country in norm_prod):
                return "出口", 1

        # ------------------ 优先级 2（车型分类规范匹配与长文本局部文字提取） ------------------
        # 2A. 直接配置通用标签/Sheet 名检测 (eg: 独立控制器, 间接式, 直接式, 直通, 爆胎)
        direct_tag_list = list(self.STANDARD_DIRECT_TAGS)
        if hasattr(self.config_mgr, "direct_tags"):
            for t in self.config_mgr.direct_tags:
                if t not in direct_tag_list and t != "胎压监测":
                    direct_tag_list.append(t)
        # 按长度降序，保证最特异的标签优先命中
        direct_tag_list.sort(key=len, reverse=True)
        for dtag in direct_tag_list:
            if dtag and len(dtag) >= 2:
                if dtag in norm_model or dtag in norm_prod:
                    return dtag, 2

        # 2B. 针对每个 Sheet 规则进行匹配（严格要求生产车系/大车系与打标型号对应）
        for sheet_name, rule in self.config_mgr.sheet_rules.items():
            major_series_rules = rule.get("major_series_rules", set())
            full_models = rule.get("full_models", set())
            code_pairs = rule.get("code_pairs", [])
            empty_code_primaries = rule.get("empty_code_primaries", set())
            model_rules = rule.get("model_rules", [])

            # 条件 2B-1: 车型长文本中直接显式包含该配置 Sheet 名（如“爆胎”、“直通”等）
            if sheet_name and len(sheet_name) >= 2 and not sheet_name.startswith("Sheet"):
                if sheet_name in norm_model or sheet_name in norm_prod:
                    return sheet_name, 2

            # -----------------------------------------------------------------
            # 模式 0: 1级大车系筛选代码匹配
            # 用户明确要求：“如果只有大车系筛选代码的整个大车系一列和sheet中匹配的话就都打标，原先的二三级筛选机制保持不变”
            # -----------------------------------------------------------------
            if major_series_rules:
                for c0 in major_series_rules:
                    # 1. 大车系一列匹配
                    if norm_series_a and self.is_prod_series_match(norm_series_a, c0):
                        return sheet_name, 2
                    # 2. 生产车系一列匹配（即使大车系列无值或有别名，生产车系等于该大车系代码也命中）
                    if norm_prod and self.is_prod_series_match(norm_prod, c0):
                        return sheet_name, 2
                    # 3. 车型列直接包含该大车系代码
                    if norm_model and re.search(rf'(?<![A-Za-z0-9]){re.escape(c0)}(?:[-_/\(\[（【]|(?![A-Za-z0-9]))', norm_model, re.IGNORECASE):
                        return sheet_name, 2

            # -----------------------------------------------------------------
            # 核心匹配原则：生产车系必须与规范的2级生产车系代码一一对应！
            # -----------------------------------------------------------------

            # 模式 1: 优先依据单行结构化规则 (model_rules: c0 + c1 + c2 + model_name) 进行精确匹配
            if model_rules:
                # 步骤 1A: 优先匹配只有 1级大车系筛选代码的规则
                for mr in model_rules:
                    c0_rule = mr.get("c0", "")
                    c1_rule = mr.get("c1", "")
                    c2_rule = mr.get("c2", "")
                    m_name_rule = mr.get("model_name", "")
                    if c0_rule and not c1_rule and not c2_rule:
                        if norm_series_a and self.is_prod_series_match(norm_series_a, c0_rule):
                            return sheet_name, 2
                        if norm_prod and self.is_prod_series_match(norm_prod, c0_rule):
                            return sheet_name, 2
                        if norm_model and re.search(rf'(?<![A-Za-z0-9]){re.escape(c0_rule)}(?:[-_/\(\[（【]|(?![A-Za-z0-9]))', norm_model, re.IGNORECASE):
                            return sheet_name, 2
                        # 车型全称/名称双向匹配 (如规范中“海狮08”、“大汉-底盘”)
                        if m_name_rule:
                            clean_mn = self.normalize_text(m_name_rule)
                            if clean_mn and len(clean_mn) >= 2:
                                if norm_series_a and (clean_mn in norm_series_a or norm_series_a in clean_mn):
                                    return sheet_name, 2
                                if norm_model and (clean_mn in norm_model or norm_model in clean_mn):
                                    return sheet_name, 2
                                # 剥离“-底盘”、“-电器”、“-车身”等科室/平台后缀后的核心车系名 (如“大汉-底盘” -> “大汉”)
                                clean_mn_core = re.sub(r'[-_/\s\(\)（）]+(底盘|电器|车身|总装|内外饰|电子|动力|电池|换代)$', '', clean_mn).strip()
                                if clean_mn_core and len(clean_mn_core) >= 2 and clean_mn_core != clean_mn:
                                    if norm_series_a and (clean_mn_core in norm_series_a or norm_series_a in clean_mn_core):
                                        return sheet_name, 2
                                    if norm_prod and (clean_mn_core in norm_prod or norm_prod in clean_mn_core):
                                        return sheet_name, 2
                                    if norm_model and (clean_mn_core in norm_model or norm_model in clean_mn_core):
                                        return sheet_name, 2

                # 步骤 1B: 匹配只有 2级生产车系代码、没有 3级车型代码的规则 (原 1级车型代码)
                # 用户明确指示：“如果只有一级代码，没有二级代码，需要总表中生产车系一列和一级车型代码匹配，则属于该sheet分类，比如爆胎”
                for mr in model_rules:
                    c1_rule = mr.get("c1", "")
                    c2_rule = mr.get("c2", "")
                    m_name_rule = mr.get("model_name", "")
                    if not c2_rule and c1_rule:
                        if norm_prod and self.is_prod_series_match(norm_prod, c1_rule):
                            return sheet_name, 2
                        elif not norm_prod:
                            if m_name_rule:
                                norm_mnr = self.normalize_text(m_name_rule)
                                if norm_mnr and (norm_mnr in norm_model or norm_mnr == display_text):
                                    return sheet_name, 2
                            elif len(c1_rule) >= 3 and re.search(rf'(?<![A-Za-z0-9]){re.escape(c1_rule)}(?:[-_/]|(?![A-Za-z0-9]))', norm_model, re.IGNORECASE):
                                return sheet_name, 2

                # 步骤 1C: 匹配同时包含 2级生产车系代码与 3级车型代码的细分型号 (c1 + c2)
                for mr in model_rules:
                    c1_rule = mr.get("c1", "")
                    c2_rule = mr.get("c2", "")
                    if c2_rule:
                        if c1_rule:
                            if norm_prod:
                                if not self.is_prod_series_match(norm_prod, c1_rule):
                                    continue
                            else:
                                if len(c1_rule) < 2 or not re.search(rf'(?<![A-Za-z0-9]){re.escape(c1_rule)}[-_/\(\[（【]', norm_model, re.IGNORECASE):
                                    continue
                        # 如果表格显式包含三级车型代码，直接进行代码比对
                        if norm_c2:
                            c2_clean = re.sub(r'[型款版]$', '', norm_c2).strip()
                            r2_clean = re.sub(r'[型款版]$', '', c2_rule).strip()
                            if (norm_c2 == c2_rule or c2_clean == r2_clean or 
                                (norm_c2.isdigit() and c2_rule.isdigit() and int(norm_c2) == int(c2_rule))):
                                return sheet_name, 2
                        if self.matches_secondary_code(norm_model, c2_rule, c1_rule, display_text):
                            return sheet_name, 2

            # 模式 2: 匹配 code_pairs: (c1, c2)
            for c1, c2 in code_pairs:
                c1_norm = self.normalize_text(c1)
                c2_norm = self.normalize_text(c2)
                if not c1_norm:
                    continue

                # 必须严格验证生产车系一一对应！绝不能出现只检测车型列的情况！
                has_c1 = False
                if norm_prod:
                    has_c1 = self.is_prod_series_match(norm_prod, c1_norm)
                else:
                    if len(c1_norm) >= 2 and re.search(rf'(?<![A-Za-z0-9]){re.escape(c1_norm)}[-_/\(\[（【]', norm_model, re.IGNORECASE):
                        has_c1 = True

                if has_c1:
                    if not c2_norm:
                        return sheet_name, 2
                    if norm_c2:
                        c2_clean = re.sub(r'[型款版]$', '', norm_c2).strip()
                        r2_clean = re.sub(r'[型款版]$', '', c2_norm).strip()
                        if (norm_c2 == c2_norm or c2_clean == r2_clean or 
                            (norm_c2.isdigit() and c2_norm.isdigit() and int(norm_c2) == int(c2_norm))):
                            return sheet_name, 2
                    if self.matches_secondary_code(norm_model, c2_norm, c1_norm, display_text):
                        return sheet_name, 2
                elif c2_norm and len(c1_norm) >= 3:
                    # 如果生产车系未直接匹配，但车型列显式包含了完整复合型号（如“前驱EWEK-20旗舰型”包含 EWEK 与 20，且代码长度>=3防短代码误判）
                    pattern_combo = rf'(?<![A-Za-z0-9]){re.escape(c1_norm)}\s*[-_/\(\[（【]?\s*{re.escape(c2_norm)}(?:[\)\]）】"\'型款版\w]*)'
                    if re.search(pattern_combo, norm_model, re.IGNORECASE):
                        return sheet_name, 2

            # 模式 3: 匹配 empty_code_primaries: c1 (二级代码为空的一级代码)
            # 用户明确要求：总表中生产车系一列和一级车型代码完全匹配即命中
            for c1_empty in empty_code_primaries:
                if not c1_empty:
                    continue
                if norm_prod:
                    if self.is_prod_series_match(norm_prod, c1_empty):
                        return sheet_name, 2
                else:
                    c1_norm = self.normalize_text(c1_empty)
                    if len(c1_norm) >= 3 and re.search(rf'(?<![A-Za-z0-9]){re.escape(c1_norm)}(?![A-Za-z0-9])', norm_model, re.IGNORECASE):
                        return sheet_name, 2

            # 模式 4: 车型全称独立匹配 (仅当模型名具备明确独立型号格式如 EWEK-10型 时匹配)
            # 用户严正要求：生产车系一列必须与打标型号一一对应，生产车系有值时绝不允许绕过生产车系“只检测车型列”！
            if not norm_prod:
                for fm in full_models:
                    if not fm:
                        continue
                    norm_fm = self.normalize_text(fm)
                    if not norm_fm or len(norm_fm) < 4:
                        continue
                    if re.search(r'[A-Za-z0-9]{2,}[-_/]\d+', norm_fm):
                        if norm_fm in norm_model or norm_fm == display_text:
                            return sheet_name, 2

        # ------------------ 优先级 3 ------------------
        # 未设计的行，配置列留空
        return "", 3

    def tag_dataframe(
        self,
        df: pd.DataFrame,
        prod_series_col: str = "生产车系",
        model_col: str = "车型",
        series_a_col: Optional[str] = None,
        drop_totals: bool = True
    ) -> pd.DataFrame:
        """
        对整个 DataFrame 执行打标：
        1. 自动处理 Excel 合并单元格，确保大车系正确填充，防止合计行破坏分类归属
        2. 自动剔除包含“合计”、“总计”、“小计”、“常规”及基地合计等非数据汇总行
        3. 清洗并同步修改“车型”列，去除 (普通)、(选装激光雷达)、试验 等多余噪声
        4. 在最后一列追加或填充“配置”列
        """
        df_res = df.copy()

        # 智能全兼容匹配列名（支持去除空格标点、兼容规范表头与月计划表头所有变体）
        def _match_col(candidates, exclude_cols=None):
            exclude_clean = [re.sub(r'[\s\(\)（）_\-\[\]【】/\\.:：]+', '', str(x)).lower() for x in (exclude_cols or [])]
            # 1. 严格清洗后完全相等匹配
            for cand in candidates:
                cand_clean = re.sub(r'[\s\(\)（）_\-\[\]【】/\\.:：]+', '', cand).lower()
                for c in df_res.columns:
                    c_clean = re.sub(r'[\s\(\)（）_\-\[\]【】/\\.:：]+', '', str(c)).lower()
                    if c_clean in exclude_clean:
                        continue
                    if c_clean == cand_clean:
                        return c
            # 2. 包含关键词匹配 (注意：必须是候选词作为子串出现在列名中，绝不能反过来让短名称匹配到长名称！)
            for cand in candidates:
                cand_clean = re.sub(r'[\s\(\)（）_\-\[\]【】/\\.:：]+', '', cand).lower()
                for c in df_res.columns:
                    c_clean = re.sub(r'[\s\(\)（）_\-\[\]【】/\\.:：]+', '', str(c)).lower()
                    if c_clean in exclude_clean:
                        continue
                    if cand_clean and cand_clean in c_clean:
                        return c
            return None

        actual_a_col = _match_col(([series_a_col] if series_a_col else []) + [
            "一级大车系筛选代码", "1级大车系筛选代码", "大车系筛选代码", "一级大车系", "1级大车系", "大车系代码", "大车系", "车系分类", "车系大类"
        ])

        actual_prod_col = _match_col([
            prod_series_col, "二级生产车系筛选代码", "2级生产车系筛选代码", "生产车系筛选代码", "生产车系代码",
            "二级生产车系", "2级生产车系", "生产车系", "一级车型代码", "一级车系", "车系代号", "生产车型", "车型代码", "车系代码", "车系名称", "车系"
        ])

        # 车型全称/车型名称列（优先完整车型名称，绝不与三级代码混淆）
        actual_model_col = _match_col([
            "车型", "车型名称", "车型全称", "完整车型", model_col, "二级车型", "车系型号"
        ])

        # 独立查找三级车型筛选代码列
        actual_c2_col = _match_col([
            "三级车型筛选代码", "3级车型筛选代码", "车型筛选代码", "三级车型代码", "3级车型代码", "三级代码", "3级代码", "二级车型代码", "二级代码"
        ], exclude_cols=[actual_model_col])

        # 如果没有单独的车型名称列，回退到三级车型筛选代码列
        if not actual_model_col and actual_c2_col:
            actual_model_col = actual_c2_col
            actual_c2_col = None

        if not actual_model_col and not actual_a_col and not actual_prod_col:
            raise ValueError(f"数据表中未找到有效车型或车系列（可选列名: 车型, 车型名称, 一级大车系筛选代码, 二级生产车系筛选代码）")

        # 关键步骤 1: 必须在剔除合计行之前处理大车系及生产车系的合并单元格前向填充！
        # 真实数据中（如现场图片《★秘密★长沙-月计划》），合并单元格首行往往对应“生产车系=合计”。
        # 若先删合计行，所属大车系名称将被彻底删除，导致后续车型大车系完全继承错误。
        is_rule_like_table = any("筛选代码" in str(c) for c in df_res.columns)
        if not is_rule_like_table:
            if actual_a_col and actual_a_col in df_res.columns:
                # 过滤掉非车系的干扰文字（如“长沙基地合计”、“基地合计”、“常规”等），不让其向下填充
                for idx in df_res.index:
                    val = df_res.at[idx, actual_a_col]
                    if pd.notna(val):
                        val_s = str(val).strip()
                        if "基地合计" in val_s or val_s == "常规" or (val_s in ["合计", "总计", "小计"] and (not actual_prod_col or pd.isna(df_res.at[idx, actual_prod_col]))):
                            df_res.at[idx, actual_a_col] = None
                df_res[actual_a_col] = df_res[actual_a_col].ffill()

            # 同样处理生产车系的合并单元格
            if actual_prod_col and actual_prod_col in df_res.columns:
                for idx in df_res.index:
                    val = df_res.at[idx, actual_prod_col]
                    if pd.notna(val):
                        val_s = str(val).strip()
                        if any(kw in val_s for kw in ["合计", "总计", "小计", "常规", "基地合计"]):
                            df_res.at[idx, actual_prod_col] = None
                df_res[actual_prod_col] = df_res[actual_prod_col].ffill()

        # 关键步骤 2: 剔除基地汇总行、合计行及无效行
        if drop_totals:
            def _is_invalid_row(row: pd.Series) -> bool:
                # 检查首列是否为基地汇总
                col0 = str(row.iloc[0]).strip() if len(row) > 0 and pd.notna(row.iloc[0]) else ""
                if any(kw in col0 for kw in ["基地合计", "基地总计", "总合计"]):
                    return True

                # 检查车型列是否为空或为合计汇总
                if actual_model_col and actual_model_col in row.index:
                    m_val = row[actual_model_col]
                    if pd.isna(m_val) or not str(m_val).strip() or str(m_val).strip().lower() in ["nan", "none"]:
                        return True
                    m_str = str(m_val).strip()
                    if any(kw in m_str for kw in ["合计", "总计", "小计", "汇总"]):
                        return True

                # 检查生产车系列
                if actual_prod_col and actual_prod_col in row.index:
                    p_val = row[actual_prod_col]
                    if pd.notna(p_val):
                        p_str = str(p_val).strip()
                        if any(kw in p_str for kw in ["合计", "总计", "小计", "基地合计", "基地总计"]):
                            return True

                # 检查大车系列
                if actual_a_col and actual_a_col in row.index:
                    a_val = row[actual_a_col]
                    if pd.notna(a_val):
                        a_str = str(a_val).strip()
                        if any(kw in a_str for kw in ["基地合计", "基地总计", "总合计"]):
                            return True
                        if a_str == "常规" and (not actual_prod_col or pd.isna(row[actual_prod_col])):
                            return True

                return False

            mask_keep = ~df_res.apply(_is_invalid_row, axis=1)
            df_res = df_res[mask_keep].reset_index(drop=True)

        # 关键步骤 3: 保留原车型列完整信息，评估并生成配置打标
        config_values = []

        for _, row in df_res.iterrows():
            prod_val = str(row[actual_prod_col]).strip() if actual_prod_col and pd.notna(row[actual_prod_col]) else ""
            model_val = str(row[actual_model_col]).strip() if actual_model_col and pd.notna(row[actual_model_col]) else ""
            a_val = str(row[actual_a_col]).strip() if actual_a_col and pd.notna(row[actual_a_col]) else ""
            c2_val = str(row[actual_c2_col]).strip() if actual_c2_col and pd.notna(row[actual_c2_col]) else ""

            # 执行三级打标评估（内部自动提取核心型号进行规则匹配，不破坏原车型列完整信息）
            tag_res, _ = self.evaluate_row(prod_val, model_val, a_val, c2_val)
            config_values.append(tag_res)

        # 确保车型列保存完整信息（仅清理首尾多余空白，保留原汁原味的所有选装、试验、版本等完整信息）
        if actual_model_col:
            df_res[actual_model_col] = df_res[actual_model_col].apply(lambda x: str(x).strip() if pd.notna(x) else "")
        # 在表格最后一列补充表头为“配置”的数据
        df_res["配置"] = config_values
        return df_res

