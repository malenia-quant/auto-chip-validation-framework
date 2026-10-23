"""配置与参考规范管理模块 (ConfigManager)

负责加载、校验以及自动生成：
1. 《车型分类规范.xlsx》（包含各配置 Sheet，如“爆胎”，内含车型全称、一级车型代码、二级车型代码）
2. 《国家列表.xlsx》（包含全世界所有国家及其常用中文简称，如沙特阿拉伯/沙特、阿联酋、印尼、澳洲等）
"""

import os
import sys
import re
from typing import Dict, List, Set, Any, Optional
import pandas as pd


class ConfigManager:
    """管理车型分类规范与国家列表的加载与校验"""

    def __init__(self, model_spec_path: Optional[str] = None, country_list_path: Optional[str] = None):
        self.model_spec_path = model_spec_path
        self.country_list_path = country_list_path

        # 缓存结构:
        # sheet_rules: {
        #     sheet_name: {
        #         "full_models": Set[str],  # 车型全称/分类列表, eg: {"EWEK-10型", "EWEK-10"}
        #         "code_pairs": List[tuple[str, str]],  # (一级车型代码, 二级车型代码), eg: [("EWEK", "10")]
        #         "empty_code_primaries": Set[str],  # 二级车型代码为空的一级代码集合, eg: {"SNED"}
        #     }
        # }
        self.sheet_rules: Dict[str, Dict[str, Any]] = {}
        # 支持上一版 (大车系, 车型/车系) -> 分类 映射字典
        self.ref_map: Dict[Tuple[str, str], str] = {}
        # 直接配置标签（包含所有 sheet 名及行业常用直接配置名称）
        self.direct_tags: Set[str] = {"爆胎", "直接式", "间接式", "独立控制器", "直通", "胎压监测"}
        self.countries: List[str] = []

        candidates_dirs = []
        if getattr(sys, 'frozen', False):
            candidates_dirs.append(os.path.join(os.path.dirname(sys.executable), "data"))
            if hasattr(sys, '_MEIPASS'):
                candidates_dirs.append(os.path.join(sys._MEIPASS, "data"))
        else:
            candidates_dirs.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))

        if model_spec_path and os.path.exists(model_spec_path):
            self.load_model_spec(model_spec_path)
        elif not model_spec_path:
            for b_dir in candidates_dirs:
                for s_name in ["车型分类规范.xlsx", "车型分类规范.xls"]:
                    candidate = os.path.join(b_dir, s_name)
                    if os.path.exists(candidate):
                        try:
                            self.load_model_spec(candidate)
                            break
                        except Exception:
                            pass
                if self.sheet_rules:
                    break

        if country_list_path and os.path.exists(country_list_path):
            self.load_country_list(country_list_path)
        elif not country_list_path:
            for b_dir in candidates_dirs:
                for c_name in ["地区列表.xlsx", "国家列表.xlsx", "地区列表.xls", "国家列表.xls"]:
                    candidate = os.path.join(b_dir, c_name)
                    if os.path.exists(candidate):
                        try:
                            self.load_country_list(candidate)
                            break
                        except Exception:
                            pass
                if self.countries:
                    break

    def load_model_spec(self, file_path: str) -> Dict[str, Dict[str, Any]]:
        """
        加载《车型分类规范.xlsx》，具备全自动智能表头检测与一级/二级代码识别能力：
        1. 自动扫描各 Sheet 前 10 行，根据表头关键字加权得分智能定位真实表头行，支持标题栏、复合/合并表头与空行。
        2. 全面支持多格式一级代码（一级代码、一级车型代码、生产车系代码、车系代码、车型一级代码、一级车系、一级、车型代码(一级)等）
           与二级代码（二级代码、二级车型代码、车型代码、车型二级代码、二级车型、二级、车型代码(二级)等）。
        3. 完美兼容多种规范组织架构：
           - 架构 A（多 Sheet 式）：每个 Sheet 名代表一种配置分类（如“直接式”、“间接式”、“爆胎”、“独立控制器”）。
           - 架构 B（单 Sheet / 行内配置列式）：表格内部包含“配置”/“分类”/“类型”等列，逐行定义各车型的所属分类。
           - 架构 C（混合式）：优先使用行内配置列，缺省则回退至工作表分类。
        4. 彻底重置历史规则，防止旧文件旧规则残留污染。
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"车型分类规范文件不存在: {file_path}")

        sheet_rules: Dict[str, Dict[str, Any]] = {}
        ref_map: Dict[Tuple[str, str], str] = {}
        direct_tags: Set[str] = set()

        def _score_header_row(row_vals: List[str]) -> int:
            score = 0
            for v in row_vals:
                s = re.sub(r'[\s\(\)（）_\-\[\]【】/\\.:：]+', '', str(v)).lower()
                if s in ['一级大车系筛选代码', '1级大车系筛选代码', '二级生产车系筛选代码', '2级生产车系筛选代码', '三级车型筛选代码', '3级车型筛选代码', '车型名称']:
                    score += 20
                elif any(k in s for k in ["一级", "1级", "二级", "2级", "三级", "3级", "c1", "c2", "c3", "大车系", "生产车系"]):
                    score += 5
                elif any(k in s for k in ["代码", "code", "代号", "编号", "标识", "筛选"]):
                    score += 4
                elif any(k in s for k in ["车型", "车系", "生产车系"]):
                    score += 3
                elif any(k in s for k in ["配置", "分类", "类别", "类型", "方案"]):
                    score += 2
                elif any(k in s for k in ["型号", "名称", "备注"]):
                    score += 1
            return score

        def _score_c0_col(c_name: str) -> int:
            clean = re.sub(r'[\s\(\)（）_\-\[\]【】/\\.:：]+', '', str(c_name)).lower()
            if any(k in clean for k in ['生产车系', '车型代码', '二级', '2级', '三级', '3级', 'c1', 'c2', 'c3']):
                return 0
            # 优先精确命中“一级大车系筛选代码”及其变体
            if clean in ['一级大车系筛选代码', '1级大车系筛选代码', '大车系筛选代码', '一级大车系', '1级大车系', '大车系代码']:
                return 100
            if '大车系' in clean or '车系大类' in clean:
                if any(k in clean for k in ['筛选代码', '代码', 'code', '代号']):
                    return 100
                if any(k in clean for k in ['一级', '1级', 'c0']):
                    return 95
                return 80
            if '一级大车系' in clean or '1级大车系' in clean:
                return 100
            return 0

        def _score_c1_col(c_name: str, c0_col_name: Optional[str] = None) -> int:
            if c_name == c0_col_name:
                return 0
            clean = re.sub(r'[\s\(\)（）_\-\[\]【】/\\.:：]+', '', str(c_name)).lower()
            if '大车系' in clean:
                return 0
            # 优先精确命中“二级生产车系筛选代码”及其变体
            if clean in ['二级生产车系筛选代码', '2级生产车系筛选代码', '生产车系筛选代码', '生产车系代码', '生产车系代号', '二级生产车系', '2级生产车系']:
                return 100
            if any(k in clean for k in ['二级生产车系', '2级生产车系', '生产车系筛选代码', '生产车系代码', '生产车系代号']):
                return 100
            if '生产车系' in clean:
                return 90
            # 向下兼容历史旧表头：如果未包含“大车系”，一级车型代码/一级代码/1级代码作为生产车系
            if any(k in clean for k in ['二级', '2级', '三级', '3级', 'c2', 'c3']):
                return 0
            has_prim = any(p in clean for p in ['一级', '1级', 'c1', 'code1', 'primary'])
            has_code = any(k in clean for k in ['代码', 'code', '代号', '编号', '标识', '车型', '车系'])
            if has_prim and has_code:
                return 85
            if clean in ['一级', '1级', 'c1', 'code1', 'primary']:
                return 80
            if '车系代码' in clean:
                return 75
            if '车系' in clean and not any(k in clean for k in ['大车系', '分类', '大类', '全称']):
                return 60
            return 0

        def _score_c2_col(c_name: str, c0_col_name: Optional[str] = None, c1_col_name: Optional[str] = None) -> int:
            if c_name in [c0_col_name, c1_col_name]:
                return 0
            clean = re.sub(r'[\s\(\)（）_\-\[\]【】/\\.:：]+', '', str(c_name)).lower()
            if '大车系' in clean or '生产车系' in clean:
                return 0
            # 优先精确命中“三级车型筛选代码”及其变体
            if clean in ['三级车型筛选代码', '3级车型筛选代码', '车型筛选代码', '三级车型代码', '3级车型代码', '三级代码', '3级代码']:
                return 100
            if any(k in clean for k in ['三级车型', '3级车型', '三级代码', '3级代码', '车型筛选代码']):
                return 100
            # 向下兼容历史旧表头：“二级车型代码”、“二级代码”、“2级代码”
            has_sec = any(p in clean for p in ['二级', '2级', '三级', '3级', 'c2', 'c3', 'secondary'])
            has_code = any(k in clean for k in ['代码', 'code', '代号', '编号', '标识', '车型'])
            if has_sec and has_code:
                return 90
            if clean in ['二级', '2级', '三级', '3级', 'c2', 'c3', 'secondary']:
                return 85
            if '车型代码' in clean or '车型代号' in clean:
                return 75
            return 0

        with pd.ExcelFile(file_path) as excel:
            for sheet_name in excel.sheet_names:
                clean_sheet = str(sheet_name).strip()
                if clean_sheet in ["说明", "基础概况", "车间设备状态", "备注"]:
                    continue

                try:
                    df_raw = excel.parse(sheet_name, header=None)
                except Exception:
                    continue

                if df_raw.empty or len(df_raw) < 1:
                    continue

                # 1. 智能定位表头行 (加权得分定位真实表头行)
                best_header_row = 0
                best_score = -1
                for r in range(min(10, len(df_raw))):
                    row_vals = [str(x).strip() for x in df_raw.iloc[r] if pd.notna(x) and str(x).strip()]
                    score = _score_header_row(row_vals)
                    if score > best_score and score >= 2:
                        best_score = score
                        best_header_row = r

                # 提取表头并尝试与上一行复合表头融合
                header_cols = [str(x).strip() if pd.notna(x) else "" for x in df_raw.iloc[best_header_row]]
                if best_header_row > 0:
                    super_cols = [str(x).strip() if pd.notna(x) else "" for x in df_raw.iloc[best_header_row - 1]]
                    merged_cols = []
                    for c, sc in zip(header_cols, super_cols):
                        if (
                            sc 
                            and sc.lower() not in ["nan", "none", ""] 
                            and not sc.startswith("Unnamed")
                            and any(k in sc for k in ["代码", "车系", "车型", "配置", "生产", "大车系", "筛选"])
                            and len(sc) < 20
                            and sc != c
                        ):
                            merged_cols.append(f"{sc}_{c}")
                        else:
                            merged_cols.append(c)
                    header_cols = merged_cols

                # 构建数据部分（严禁对全表执行无差别 ffill，避免二级代码为空的规则被上一行二级代码污染！）
                df_data = df_raw.iloc[best_header_row + 1:].reset_index(drop=True)
                df_data.columns = [str(c).strip() for c in header_cols]
                df = df_data.copy()

                if df.empty:
                    continue

                # 收集非通用 Sheet 名作为直接配置标签候选
                if clean_sheet and len(clean_sheet) >= 2 and not clean_sheet.lower().startswith("sheet"):
                    direct_tags.add(clean_sheet)

                # 2. 智能识别各关键列名
                # 2-0. 1级大车系筛选代码列 (Major Series Code)
                c0_scored = [(c, _score_c0_col(c)) for c in df.columns]
                c0_scored = [x for x in c0_scored if x[1] > 0]
                c0_col = max(c0_scored, key=lambda x: x[1])[0] if c0_scored else None

                # 2A. 2级生产车系筛选代码列 (Production Series Code / Primary Code)
                c1_scored = [(c, _score_c1_col(c, c0_col)) for c in df.columns]
                c1_scored = [x for x in c1_scored if x[1] > 0]
                c1_col = max(c1_scored, key=lambda x: x[1])[0] if c1_scored else None

                # 2B. 3级车型筛选代码列 (Vehicle Model Code / Secondary Code)
                c2_scored = [(c, _score_c2_col(c, c0_col, c1_col)) for c in df.columns]
                c2_scored = [x for x in c2_scored if x[1] > 0]
                c2_col = max(c2_scored, key=lambda x: x[1])[0] if c2_scored else None

                # 2C. 行内配置分类列 (Config / Tag Column)
                def _score_config_col(c_name: str) -> int:
                    if c_name in [c0_col, c1_col, c2_col]:
                        return 0
                    clean = re.sub(r'[\s\(\)（）_\-\[\]【】/\\.:：]+', '', str(c_name)).lower()
                    if any(k in clean for k in ["车系", "大车系", "大类", "总数", "数量", "说明", "备注", "备注说明", "代码", "代号", "编号"]):
                        return 0
                    if "车型" in clean and not any(k in clean for k in ["配置", "tpms", "胎压", "方案", "传感器"]):
                        return 0
                    if any(k in clean for k in ["tpms配置", "配置分类", "传感器类型", "胎压方案", "技术路线"]):
                        return 100
                    if any(k in clean for k in ["配置", "方案", "路线", "胎压", "tpms", "传感器"]):
                        return 80
                    if any(k in clean for k in ["分类", "类别", "类型", "属性"]):
                        return 60
                    return 0

                cfg_scored = [(c, _score_config_col(c)) for c in df.columns]
                cfg_scored = [x for x in cfg_scored if x[1] > 0]
                config_col = max(cfg_scored, key=lambda x: x[1])[0] if cfg_scored else None

                # 2D. 车型全称列 (Full Model Name)
                def _score_model_col(c_name: str) -> int:
                    if c_name in [c0_col, c1_col, c2_col, config_col]:
                        return 0
                    clean = re.sub(r'[\s\(\)（）_\-\[\]【】/\\.:：]+', '', str(c_name)).lower()
                    if "代码" in clean or "车系" in clean:
                        return 0
                    if any(k in clean for k in ["车型全称", "完整车型", "车型名称"]):
                        return 100
                    if "车型" in clean or "型号" in clean:
                        return 70
                    return 0

                model_scored = [(c, _score_model_col(c)) for c in df.columns]
                model_scored = [x for x in model_scored if x[1] > 0]
                model_col = max(model_scored, key=lambda x: x[1])[0] if model_scored else None

                # 2E. 大车系列 (Series / Category)
                sheet_a_col = None
                for c in df.columns:
                    if c in [c0_col, c1_col, c2_col, config_col, model_col]:
                        continue
                    clean_c = re.sub(r'[\s\(\)（）_\-\[\]【】/\\.:：]+', '', str(c)).lower()
                    if any(k in clean_c for k in ["大车系", "车系分类", "车系大类", "一级车系"]):
                        sheet_a_col = c
                        break

                # 仅对“大车系/一级车系”等确实存在合并单元格的分类列进行向下填充
                if sheet_a_col and sheet_a_col in df.columns:
                    df[sheet_a_col] = df[sheet_a_col].ffill()

                # 如果一级代码列存在合并单元格：仅当二级代码存在且有效时才继承上一行一级代码
                if c1_col and c1_col in df.columns and c2_col and c2_col in df.columns:
                    for idx in range(1, len(df)):
                        c1_val = df.at[idx, c1_col]
                        c2_val = df.at[idx, c2_col]
                        if (pd.isna(c1_val) or not str(c1_val).strip() or str(c1_val).strip().lower() in ["nan", "none"]) and pd.notna(c2_val) and str(c2_val).strip() and str(c2_val).strip().lower() not in ["nan", "none"]:
                            df.at[idx, c1_col] = df.at[idx - 1, c1_col]

                # 3. 逐行解析规则
                for _, row in df.iterrows():
                    # 确定本行所属的目标配置分类 (Target Tag)
                    row_tag = ""
                    if config_col:
                        val_cfg = str(row.get(config_col, "")).strip()
                        if val_cfg and val_cfg.lower() not in ["nan", "none", "null"]:
                            row_tag = val_cfg

                    if not row_tag:
                        row_tag = clean_sheet

                    # 排除无效配置名
                    if not row_tag or row_tag.lower() in ["nan", "none", "null", ""]:
                        continue

                    # 处理泛化 Sheet 名（如 Sheet1, 工作表1）
                    if row_tag.lower().startswith("sheet") or row_tag.startswith("工作表"):
                        fn_base = os.path.splitext(os.path.basename(file_path))[0]
                        inferred = ""
                        for kw in ["直接式", "间接式", "独立控制器", "爆胎", "直通"]:
                            if kw in fn_base:
                                inferred = kw
                                break
                        if inferred:
                            row_tag = inferred

                    direct_tags.add(row_tag)
                    if row_tag not in sheet_rules:
                        sheet_rules[row_tag] = {
                            "major_series_rules": set(),
                            "full_models": set(),
                            "code_pairs": [],
                            "empty_code_primaries": set(),
                            "model_rules": []
                        }

                    val_a = str(row.get(sheet_a_col, "")).strip() if sheet_a_col else ""
                    if val_a.lower() in ["nan", "none"]:
                        val_a = ""

                    # 提取车型全称
                    model_name_str = ""
                    if model_col:
                        raw_model_val = str(row.get(model_col, "")).strip()
                        if raw_model_val and raw_model_val.lower() not in ["nan", "none"]:
                            model_name_str = raw_model_val
                            for sub_s in re.split(r'[\r\n;,、/]+', raw_model_val):
                                clean_sub = sub_s.strip()
                                if clean_sub and clean_sub.lower() not in ["nan", "none"]:
                                    sheet_rules[row_tag]["full_models"].add(clean_sub)
                                    if val_a:
                                        ref_map[(val_a, clean_sub)] = row_tag
                                    ref_map[("", clean_sub)] = row_tag

                    # 提取 1级大车系筛选代码 (c0)
                    c0_str = ""
                    if c0_col and c0_col in df.columns:
                        c0_raw = row.get(c0_col, "")
                        if pd.notna(c0_raw):
                            v0 = str(c0_raw).strip()
                            if re.match(r'^\d+\.0$', v0):
                                v0 = v0[:-2]
                            if v0 and v0.lower() not in ["nan", "none"] and "合计" not in v0:
                                c0_str = v0
                                if not val_a:
                                    val_a = v0

                    # 提取 2级生产车系筛选代码 (c1)
                    c1_str = ""
                    if c1_col and c1_col in df.columns:
                        c1_raw = row.get(c1_col, "")
                        if pd.notna(c1_raw):
                            v1 = str(c1_raw).strip()
                            if re.match(r'^\d+\.0$', v1):
                                v1 = v1[:-2]
                            if v1 and v1.lower() not in ["nan", "none"] and "合计" not in v1:
                                c1_str = v1

                    # 提取 3级车型筛选代码 (c2)
                    c2_str = ""
                    if c2_col and c2_col in df.columns:
                        c2_raw = row.get(c2_col, "")
                        if pd.notna(c2_raw):
                            v2 = str(c2_raw).strip()
                            if re.match(r'^\d+\.0$', v2):
                                v2 = v2[:-2]
                            if v2.lower() not in ["nan", "none"]:
                                c2_str = v2

                    # 分情况构建规则：
                    # 情况 1: 只有 1级大车系筛选代码，没有 2级和 3级代码
                    # 用户明确指示：“如果只有大车系筛选代码的整个大车系一列和sheet中匹配的话就都打标，原先的二三级筛选机制保持不变”
                    if c0_str and not c1_str and not c2_str:
                        c0_items = [x.strip() for x in re.split(r'[\r\n;,、/]+', c0_str) if x.strip()]
                        for item0 in c0_items:
                            sheet_rules[row_tag]["major_series_rules"].add(item0)
                            sheet_rules[row_tag]["model_rules"].append({
                                "c0": item0,
                                "c1": "",
                                "c2": "",
                                "model_name": model_name_str
                            })
                            ref_map[(item0, "")] = row_tag
                            ref_map[(item0, "*")] = row_tag

                    # 情况 2: 存在 2级生产车系筛选代码 (c1_str)
                    elif c1_str:
                        c1_items = [x.strip() for x in re.split(r'[\r\n;,、/]+', c1_str) if x.strip()]
                        for item1 in c1_items:
                            if not c2_str:
                                # 2级生产车系统配 (无 3级代码): 该生产车系全部属于该配置分类
                                sheet_rules[row_tag]["empty_code_primaries"].add(item1)
                                sheet_rules[row_tag]["model_rules"].append({
                                    "c0": c0_str,
                                    "c1": item1,
                                    "c2": "",
                                    "model_name": model_name_str
                                })
                                if val_a:
                                    ref_map[(val_a, item1)] = row_tag
                                ref_map[("", item1)] = row_tag
                            else:
                                # 2级 + 3级细分车型匹配
                                c2_items = [x.strip() for x in re.split(r'[\r\n;,、/]+', c2_str) if x.strip()]
                                for item2 in c2_items:
                                    # 如果二级代码里自带了一级前缀（如 item2 为 CKEB-30），剥离提取纯二级代码 30
                                    if item2.upper().startswith(item1.upper() + "-") or item2.upper().startswith(item1.upper() + "_"):
                                        clean_item2 = item2[len(item1)+1:].strip()
                                    else:
                                        clean_item2 = item2

                                    # 剥离末尾的“型”、“款”、“版”
                                    stripped_item2 = re.sub(r'[型款版]$', '', clean_item2).strip()

                                    # 将规范形式都加入匹配规则中
                                    for p_c2 in {clean_item2, stripped_item2, item2}:
                                        if p_c2:
                                            sheet_rules[row_tag]["code_pairs"].append((item1, p_c2))
                                            sheet_rules[row_tag]["model_rules"].append({
                                                "c0": c0_str,
                                                "c1": item1,
                                                "c2": p_c2,
                                                "model_name": model_name_str
                                            })
                                            combo = f"{item1}-{p_c2}"
                                            if val_a:
                                                ref_map[(val_a, combo)] = row_tag
                                            ref_map[("", combo)] = row_tag

        self.model_spec_path = file_path
        self.sheet_rules = sheet_rules
        self.ref_map = ref_map
        self.direct_tags = direct_tags
        return sheet_rules

    def load_country_list(self, file_path: str) -> List[str]:
        """
        加载《地区列表.xlsx》（兼容《国家列表.xlsx》），自动提取所有相关列（地区/国家名称、中文简称、全称、别名等），
        去重并按字符长度降序排序，确保长词优先匹配。
        支持某一行只有简称或者只有全称，均能被正常提取并加入过滤名单。
        自动排除大洲、序号、备注等辅助元数据列。
        """
        target_file = file_path
        if not os.path.exists(target_file):
            dir_name = os.path.dirname(os.path.abspath(file_path))
            for alt in ["地区列表.xlsx", "国家列表.xlsx"]:
                p_alt = os.path.join(dir_name, alt)
                if os.path.exists(p_alt):
                    target_file = p_alt
                    break

        if not os.path.exists(target_file):
            raise FileNotFoundError(f"地区/国家列表文件不存在: {file_path}")

        file_path = target_file
        with pd.ExcelFile(file_path) as excel:
            first_sheet = excel.sheet_names[0]
            df = excel.parse(first_sheet)

        if df.empty:
            self.countries = []
            return []

        df.columns = [str(c).strip() for c in df.columns]

        # 排除非国家/地区与大洲的辅助元数据列（如序号、备注、代码等）
        # 严格满足用户要求：国家/地区、常用中文简称、官方全称/别名、所属大洲（中国除外）均计入出口过滤名单
        ignore_col_keywords = ["序号", "id", "index", "备注", "说明", "continent_code", "remark", "notes", "code", "代码"]
        valid_cols = [
            c for c in df.columns
            if not any(k in c.lower() for k in ignore_col_keywords)
        ]
        if not valid_cols:
            valid_cols = list(df.columns)

        # 保护国内本土名词及不可作为出口依据的大洲/区域词（避免造成国内内销车型误伤打标为“出口”）
        # 严格遵循用户指示：“只出现亚洲或者亚太也别算”
        DOMESTIC_KEYWORDS = {"中国", "中华人民共和国", "国内", "中国大陆", "中国内地", "亚洲", "亚太"}

        country_set: Set[str] = set()

        # 逐行遍历所有有效列：国家/地区、常用中文简称、官方全称/别名、所属大洲（中国除外）
        for _, row in df.iterrows():
            for col in valid_cols:
                val = row.get(col)
                if pd.isna(val):
                    continue
                s = str(val).strip()
                if not s or s.lower() in ["nan", "none"] or s.startswith("Unnamed") or s.isdigit():
                    continue

                # 拆分可能包含的多个简称或别名（如 '乌兹/乌兹别克'、'乌兹或者乌兹别克'）
                tokens = [s]
                for sub in re.split(r'[/,、;\s]+|或者', s):
                    sub_clean = sub.strip()
                    if sub_clean:
                        tokens.append(sub_clean)

                for t in tokens:
                    if len(t) >= 2 and t not in DOMESTIC_KEYWORDS:
                        country_set.add(t)

        countries = list(country_set)
        # 按字符串长度降序排序，确保长词（如“沙特阿拉伯”）优先于短词（如“沙特”）
        countries.sort(key=len, reverse=True)
        self.country_list_path = file_path
        self.countries = countries
        return countries

    @staticmethod
    def create_default_model_spec(file_path: str) -> str:
        """自动创建标准的默认《车型分类规范.xlsx》，涵盖直接式、间接式、独立控制器、爆胎等主流配置"""
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            # 1. Sheet: 直接式
            df_direct = pd.DataFrame({
                "车系分类": ["STE(海鸥)", "STE(海鸥)", "UNE", "UNE", "UNE", "UNE", "UNE", "UNH", "UNH"],
                "生产车系": ["STEAY", "STEBU", "UNED", "UNED", "UNEJ", "UNEL", "UNEL", "UNHC", "UNHD"],
                "车型": ["STEAY尊贵型", "STEBU-10型", "UNED-20型", "UNED-30型", "UNEJ-40型", "UNEL-30型", "UNEL-40型", "UNHC-20型", "UNHD-10型"],
                "一级车型代码": ["STEAY", "STEBU", "UNED", "UNED", "UNEJ", "UNEL", "UNEL", "UNHC", "UNHD"],
                "二级车型代码": ["尊贵型", "10", "20", "30", "40", "30", "40", "20", "10"],
                "备注": ["直接式数字胎压", "标准直接式胎压", "直接式标配", "直接式高配", "直接式尊贵型", "直接式旗舰型", "直接式至尊版", "直接式中配", "直接式试验款"]
            })
            df_direct.to_excel(writer, sheet_name="直接式", index=False)

            # 2. Sheet: 间接式
            df_indirect = pd.DataFrame({
                "车系分类": ["STH(海豚)", "UNH", "UNH"],
                "生产车系": ["STHNY", "UNHC", "UNHC"],
                "车型": ["STHNY-15型", "UNHC-10型", "UNHC-15型"],
                "一级车型代码": ["STHNY", "UNHC", "UNHC"],
                "二级车型代码": ["15", "10", "15"],
                "备注": ["间接式轮速胎压", "间接式标配", "间接式高配"]
            })
            df_indirect.to_excel(writer, sheet_name="间接式", index=False)

            # 3. Sheet: 独立控制器
            df_indep = pd.DataFrame({
                "车系分类": ["UNE", "UNE", "UNH", "UNH", "海洋"],
                "生产车系": ["UNEC", "UNEK", "UNHG", "UNHG", "SEAL"],
                "车型": ["UNEC-10型", "UNEK-10型", "UNHG-30型", "UNHG-40型", "SEAL-08型"],
                "一级车型代码": ["UNEC", "UNEK", "UNHG", "UNHG", "SEAL"],
                "二级车型代码": ["10", "10", "30", "40", "08"],
                "备注": ["独立控制器高配", "独立控制器标配", "独立控制器试验款", "独立控制器旗舰款", "高性能独立控制器"]
            })
            df_indep.to_excel(writer, sheet_name="独立控制器", index=False)

            # 4. Sheet: 爆胎
            df_baotai = pd.DataFrame({
                "车系分类": ["UNE", "UNE", "仰望", "仰望", "仰望", "海洋", "钛7 改款", "宋GT-EV", "秦L-26款", "唐Pro26款", "腾势N8", "海狮06 秋季款"],
                "生产车系": ["UNEH", "UNEH", "EWEK", "EWEK", "EWEK", "EWEL", "QZH-3T", "UFE", "HA3H", "QBH", "SJH", "UGE"],
                "车型": ["UNEH-20型", "UNEH-30型", "EWEK-10型", "EWEK-20型", "EWEK-30型", "EWEL-05型", "钛7 改款", "宋GT-EV", "秦L-26款", "唐Pro26款", "腾势N8", "海狮06 秋季款"],
                "一级车型代码": ["UNEH", "UNEH", "EWEK", "EWEK", "EWEK", "EWEL", "QZH-3T", "UFE", "HA3H, E", "QBH, E", "SJH, E", "UGE"],
                "二级车型代码": ["20", "30", "10", "20", "30", "05", "", "", "", "", "", ""],
                "备注": ["爆胎应急防护", "爆胎应急旗舰", "爆胎应急防护高配", "爆胎应急防护标配", "旗舰配置", "爆胎防护标配", "爆胎标配", "爆胎标配", "爆胎标配", "爆胎标配", "爆胎标配", "爆胎标配"]
            })
            df_baotai.to_excel(writer, sheet_name="爆胎", index=False)

            # 5. Sheet: 胎压监测
            df_tpms = pd.DataFrame({
                "车系分类": ["海洋", "海洋"],
                "生产车系": ["ATTO", "ATTO"],
                "车型": ["ATTO-05型", "ATTO-05"],
                "一级车型代码": ["ATTO", "ATTO"],
                "二级车型代码": ["05", "05"],
                "备注": ["标准直接式胎压", "标准胎压监测"]
            })
            df_tpms.to_excel(writer, sheet_name="胎压监测", index=False)

        return file_path

    @staticmethod
    def create_default_country_list(file_path: str) -> str:
        """
        自动创建包含全世界所有国家与常用中文简称的标准《国家列表.xlsx》
        涵盖亚洲、欧洲、美洲、非洲、大洋洲共 197+ 个主权国家及常用别名与简称。
        """
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)

        # 结构化国家库数据：(国家全称/通称, 常用中文简称, 官方全称/别名, 所属大洲)
        country_data = [
            # 亚洲 (51)
            ("沙特阿拉伯", "沙特", "沙特阿拉伯王国", "亚洲"),
            ("阿拉伯联合酋长国", "阿联酋", "阿拉伯联合酋长国", "亚洲"),
            ("日本", "日本国", "日本版", "亚洲"),
            ("韩国", "南韩", "大韩民国", "亚洲"),
            ("朝鲜", "北朝鲜", "朝鲜民主主义人民共和国", "亚洲"),
            ("蒙古", "蒙古国", "外蒙古", "亚洲"),
            ("新加坡", "狮城", "新加坡共和国", "亚洲"),
            ("马来西亚", "大马", "马来西亚联邦", "亚洲"),
            ("印度尼西亚", "印尼", "印度尼西亚共和国", "亚洲"),
            ("泰国", "泰王国", "暹罗", "亚洲"),
            ("越南", "越方", "越南社会主义共和国", "亚洲"),
            ("老挝", "老挝", "老挝人民民主共和国", "亚洲"),
            ("柬埔寨", "柬埔寨", "柬埔寨王国", "亚洲"),
            ("缅甸", "缅甸", "缅甸联邦共和国", "亚洲"),
            ("菲律宾", "菲律宾", "菲律宾共和国", "亚洲"),
            ("文莱", "文莱", "文莱达鲁萨兰国", "亚洲"),
            ("东帝汶", "东帝汶", "东帝汶民主共和国", "亚洲"),
            ("印度", "印度", "印度共和国", "亚洲"),
            ("巴基斯坦", "巴基斯坦", "巴基斯坦伊斯兰共和国", "亚洲"),
            ("孟加拉国", "孟加拉", "孟加拉人民共和国", "亚洲"),
            ("斯里兰卡", "斯里兰卡", "斯里兰卡民主社会主义共和国", "亚洲"),
            ("马尔代夫", "马尔代夫", "马尔代夫共和国", "亚洲"),
            ("尼泊尔", "尼泊尔", "尼泊尔联邦民主共和国", "亚洲"),
            ("不丹", "不丹", "不丹王国", "亚洲"),
            ("哈萨克斯坦", "哈萨克", "哈萨克斯坦共和国", "亚洲"),
            ("乌兹别克斯坦", "乌兹/乌兹别克", "乌兹别克斯坦共和国", "亚洲"),
            ("吉尔吉斯斯坦", "吉尔吉斯", "吉尔吉斯共和国", "亚洲"),
            ("塔吉克斯坦", "塔吉克", "塔吉克斯坦共和国", "亚洲"),
            ("土库曼斯坦", "土库曼", "土库曼斯坦", "亚洲"),
            ("阿富汗", "阿富汗", "阿富汗伊斯兰酋长国", "亚洲"),
            ("伊朗", "伊朗", "伊朗伊斯兰共和国", "亚洲"),
            ("伊拉克", "伊拉克", "伊拉克共和国", "亚洲"),
            ("卡塔尔", "卡塔尔", "卡塔尔国", "亚洲"),
            ("科威特", "科威特", "科威特国", "亚洲"),
            ("巴林", "巴林", "巴林王国", "亚洲"),
            ("阿曼", "阿曼", "阿曼苏丹国", "亚洲"),
            ("也门", "也门", "也门共和国", "亚洲"),
            ("叙利亚", "叙利亚", "叙利亚阿拉伯共和国", "亚洲"),
            ("约旦", "约旦", "约旦哈希姆王国", "亚洲"),
            ("黎巴嫩", "黎巴嫩", "黎巴嫩共和国", "亚洲"),
            ("以色列", "以色列", "以色列国", "亚洲"),
            ("巴勒斯坦", "巴勒斯坦", "巴勒斯坦国", "亚洲"),
            ("土耳其", "土耳其", "土耳其共和国", "亚洲"),
            ("塞浦路斯", "塞浦路斯", "塞浦路斯共和国", "亚洲"),
            ("格鲁吉亚", "格鲁吉亚", "格鲁吉亚", "亚洲"),
            ("亚美尼亚", "亚美尼亚", "亚美尼亚共和国", "亚洲"),
            ("阿塞拜疆", "阿塞拜疆", "阿塞拜疆共和国", "亚洲"),
            ("中国", "中国", "中华人民共和国", "亚洲"),
            ("中国香港", "香港", "香港特别行政区", "亚洲"),
            ("中国澳门", "澳门", "澳门特别行政区", "亚洲"),
            ("中国台湾", "台湾", "台湾地区", "亚洲"),

            # 欧洲 (45)
            ("俄罗斯", "俄联邦", "俄罗斯联邦", "欧洲"),
            ("德国", "德意志", "德意志联邦共和国", "欧洲"),
            ("英国", "联合王国", "大不列颠及北爱尔兰联合王国", "欧洲"),
            ("法国", "法兰西", "法兰西共和国", "欧洲"),
            ("意大利", "意国", "意大利共和国", "欧洲"),
            ("西班牙", "西班牙", "西班牙王国", "欧洲"),
            ("葡萄牙", "葡萄牙", "葡萄牙共和国", "欧洲"),
            ("荷兰", "荷兰", "荷兰王国", "欧洲"),
            ("比利时", "比利时", "比利时王国", "欧洲"),
            ("卢森堡", "卢森堡", "卢森堡大公国", "欧洲"),
            ("瑞士", "瑞士", "瑞士联邦", "欧洲"),
            ("奥地利", "奥地利", "奥地利共和国", "欧洲"),
            ("挪威", "挪威", "挪威王国", "欧洲"),
            ("瑞典", "瑞典", "瑞典王国", "欧洲"),
            ("丹麦", "丹麦", "丹麦王国", "欧洲"),
            ("芬兰", "芬兰", "芬兰共和国", "欧洲"),
            ("冰岛", "冰岛", "冰岛共和国", "欧洲"),
            ("爱尔兰", "爱尔兰", "爱尔兰共和国", "欧洲"),
            ("希腊", "希腊", "希腊共和国", "欧洲"),
            ("波兰", "波兰", "波兰共和国", "欧洲"),
            ("捷克", "捷克", "捷克共和国", "欧洲"),
            ("斯洛伐克", "斯洛伐克", "斯洛伐克共和国", "欧洲"),
            ("匈牙利", "匈牙利", "匈牙利", "欧洲"),
            ("罗马尼亚", "罗马尼亚", "罗马尼亚", "欧洲"),
            ("保加利亚", "保加利亚", "保加利亚共和国", "欧洲"),
            ("塞尔维亚", "塞尔维亚", "塞尔维亚共和国", "欧洲"),
            ("克罗地亚", "克罗地亚", "克罗地亚共和国", "欧洲"),
            ("斯洛文尼亚", "斯洛文尼亚", "斯洛文尼亚共和国", "欧洲"),
            ("波斯尼亚和黑塞哥维那", "波黑", "波黑联邦", "欧洲"),
            ("黑山", "黑山", "黑山共和国", "欧洲"),
            ("北马其顿", "马其顿", "北马其顿共和国", "欧洲"),
            ("阿尔巴尼亚", "阿尔巴尼亚", "阿尔巴尼亚共和国", "欧洲"),
            ("乌克兰", "乌克兰", "乌克兰", "欧洲"),
            ("白俄罗斯", "白俄罗斯", "白俄罗斯共和国", "欧洲"),
            ("立陶宛", "立陶宛", "立陶宛共和国", "欧洲"),
            ("拉脱维亚", "拉脱维亚", "拉脱维亚共和国", "欧洲"),
            ("爱沙尼亚", "爱沙尼亚", "爱沙尼亚共和国", "欧洲"),
            ("摩尔多瓦", "摩尔多瓦", "摩尔多瓦共和国", "欧洲"),
            ("马耳他", "马耳他", "马耳他共和国", "欧洲"),
            ("安道尔", "安道尔", "安道尔公国", "欧洲"),
            ("圣马力诺", "圣马力诺", "圣马力诺共和国", "欧洲"),
            ("摩纳哥", "摩纳哥", "摩纳哥公国", "欧洲"),
            ("列支敦士登", "列支敦士登", "列支敦士登公国", "欧洲"),
            ("梵蒂冈", "教廷", "梵蒂冈城国", "欧洲"),
            ("科索沃", "科索沃", "科索沃共和国", "欧洲"),

            # 美洲 (41)
            ("美国", "美利坚", "美利坚合众国", "美洲"),
            ("加拿大", "加国", "加拿大", "美洲"),
            ("墨西哥", "墨西哥", "墨西哥合众国", "美洲"),
            ("巴西", "巴西", "巴西联邦共和国", "美洲"),
            ("阿根廷", "阿根廷", "阿根廷共和国", "美洲"),
            ("智利", "智利", "智利共和国", "美洲"),
            ("秘鲁", "秘鲁", "秘鲁共和国", "美洲"),
            ("哥伦比亚", "哥伦比亚", "哥伦比亚共和国", "美洲"),
            ("委内瑞拉", "委内瑞拉", "委内瑞拉玻利瓦尔共和国", "美洲"),
            ("厄瓜多尔", "厄瓜多尔", "厄瓜多尔共和国", "美洲"),
            ("乌拉圭", "乌拉圭", "乌拉圭东岸共和国", "美洲"),
            ("巴拉圭", "巴拉圭", "巴拉圭共和国", "美洲"),
            ("玻利维亚", "玻利维亚", "多民族玻利维亚国", "美洲"),
            ("古巴", "古巴", "古巴共和国", "美洲"),
            ("牙买加", "牙买加", "牙买加", "美洲"),
            ("巴拿马", "巴拿马", "巴拿马共和国", "美洲"),
            ("哥斯达黎加", "哥斯达黎加", "哥斯达黎加共和国", "美洲"),
            ("多米尼加", "多米尼加", "多米尼加共和国", "美洲"),
            ("多米尼克", "多米尼克", "多米尼克国", "美洲"),
            ("危地马拉", "危地马拉", "危地马拉共和国", "美洲"),
            ("萨尔瓦多", "萨尔瓦多", "萨尔瓦多共和国", "美洲"),
            ("洪都拉斯", "洪都拉斯", "洪都拉斯共和国", "美洲"),
            ("尼加拉瓜", "尼加拉瓜", "尼加拉瓜共和国", "美洲"),
            ("海地", "海地", "海地共和国", "美洲"),
            ("巴哈马", "巴哈马", "巴哈马国", "美洲"),
            ("巴巴多斯", "巴巴多斯", "巴巴多斯", "美洲"),
            ("特立尼达和多巴哥", "特多", "特立尼达和多巴哥共和国", "美洲"),
            ("安提瓜和巴布达", "安巴", "安提瓜和巴布达", "美洲"),
            ("格林纳达", "格林纳达", "格林纳达", "美洲"),
            ("圣基茨和尼维斯", "圣基茨", "圣基茨和尼维斯联邦", "美洲"),
            ("圣卢西亚", "圣卢西亚", "圣卢西亚", "美洲"),
            ("圣文森特和格林纳丁斯", "圣文森特", "圣文森特和格林纳丁斯", "美洲"),
            ("圭亚那", "圭亚那", "圭亚那合作共和国", "美洲"),
            ("苏里南", "苏里南", "苏里南共和国", "美洲"),
            ("伯利兹", "伯利兹", "伯利兹", "美洲"),
            ("波多黎各", "波多黎各", "波多黎各自由邦", "美洲"),
            ("格陵兰", "格陵兰", "格陵兰岛", "美洲"),
            ("百慕大", "百慕大", "百慕大群岛", "美洲"),
            ("开曼群岛", "开曼", "开曼群岛", "美洲"),
            ("库拉索", "库拉索", "库拉索", "美洲"),
            ("阿鲁巴", "阿鲁巴", "阿鲁巴", "美洲"),
            ("博奈尔岛", "博奈尔/博内尔", "博奈尔岛/荷属加勒比", "美洲"),

            # 大洋洲 (17)
            ("澳大利亚", "澳洲", "澳大利亚联邦", "大洋洲"),
            ("新西兰", "纽西兰", "新西兰", "大洋洲"),
            ("巴布亚新几内亚", "巴新", "巴布亚新几内亚独立国", "大洋洲"),
            ("斐济", "斐济", "斐济共和国", "大洋洲"),
            ("所罗门群岛", "所罗门", "所罗门群岛", "大洋洲"),
            ("瓦努阿图", "瓦努阿图", "瓦努阿图共和国", "大洋洲"),
            ("萨摩亚", "萨摩亚", "萨摩亚独立国", "大洋洲"),
            ("密克罗尼西亚", "密克", "密克罗尼西亚联邦", "大洋洲"),
            ("基里巴斯", "基里巴斯", "基里巴斯共和国", "大洋洲"),
            ("帕劳", "帕劳", "帕劳共和国", "大洋洲"),
            ("汤加", "汤加", "汤加王国", "大洋洲"),
            ("图瓦卢", "图瓦卢", "图瓦卢", "大洋洲"),
            ("瑙鲁", "瑙鲁", "瑙鲁共和国", "大洋洲"),
            ("马绍尔群岛", "马绍尔", "马绍尔群岛共和国", "大洋洲"),
            ("库克群岛", "库克", "库克群岛", "大洋洲"),
            ("纽埃", "纽埃", "纽埃", "大洋洲"),
            ("关岛", "关岛", "关岛", "大洋洲"),
            ("新喀里多尼亚", "新喀里多尼亚", "新喀里多尼亚（法国海外属地）", "大洋洲"),
            ("波利尼西亚", "波利尼西亚", "法属波利尼西亚（法国海外属地）", "大洋洲"),
            ("法属波利尼西亚", "波利尼西亚", "法属波利尼西亚", "大洋洲"),

            # 非洲 (56)
            ("埃及", "埃及", "阿拉伯埃及共和国", "非洲"),
            ("南非", "南非", "南非共和国", "非洲"),
            ("阿尔及利亚", "阿尔及利亚", "阿尔及利亚民主人民共和国", "非洲"),
            ("摩洛哥", "摩洛哥", "摩洛哥王国", "非洲"),
            ("突尼斯", "突尼斯", "突尼斯共和国", "非洲"),
            ("利比亚", "利比亚", "利比亚国", "非洲"),
            ("苏丹", "苏丹", "苏丹共和国", "非洲"),
            ("南苏丹", "南苏丹", "南苏丹共和国", "非洲"),
            ("埃塞俄比亚", "埃塞", "埃塞俄比亚联邦民主共和国", "非洲"),
            ("肯尼亚", "肯尼亚", "肯尼亚共和国", "非洲"),
            ("坦桑尼亚", "坦桑", "坦桑尼亚联合共和国", "非洲"),
            ("乌干达", "乌干达", "乌干达共和国", "非洲"),
            ("卢旺达", "卢旺达", "卢旺达共和国", "非洲"),
            ("布隆迪", "布隆迪", "布隆迪共和国", "非洲"),
            ("索马里", "索马里", "索马里联邦共和国", "非洲"),
            ("吉布提", "吉布提", "吉布提共和国", "非洲"),
            ("厄立特里亚", "厄立特里亚", "厄立特里亚国", "非洲"),
            ("尼日利亚", "尼日利亚", "尼日利亚联邦共和国", "非洲"),
            ("加纳", "加纳", "加纳共和国", "非洲"),
            ("科特迪瓦", "科特迪瓦", "科特迪瓦共和国", "非洲"),
            ("塞内加尔", "塞内加尔", "塞内加尔共和国", "非洲"),
            ("喀麦隆", "喀麦隆", "喀麦隆共和国", "非洲"),
            ("加蓬", "加蓬", "加蓬共和国", "非洲"),
            ("刚果共和国", "刚果（布）", "刚果共和国", "非洲"),
            ("刚果民主共和国", "刚果（金）", "刚果民主共和国", "非洲"),
            ("安哥拉", "安哥拉", "安哥拉共和国", "非洲"),
            ("赞比亚", "赞比亚", "赞比亚共和国", "非洲"),
            ("津巴布韦", "津巴布韦", "津巴布韦共和国", "非洲"),
            ("莫桑比克", "莫桑比克", "莫桑比克共和国", "非洲"),
            ("马达加斯加", "马达加斯加", "马达加斯加共和国", "非洲"),
            ("纳米比亚", "纳米比亚", "纳米比亚共和国", "非洲"),
            ("博茨瓦纳", "博茨瓦纳", "博茨瓦纳共和国", "非洲"),
            ("毛里求斯", "毛里求斯", "毛里求斯共和国", "非洲"),
            ("塞舌尔", "塞舌尔", "塞舌尔共和国", "非洲"),
            ("几内亚", "几内亚", "几内亚共和国", "非洲"),
            ("马里", "马里", "马里共和国", "非洲"),
            ("尼日尔", "尼日尔", "尼日尔共和国", "非洲"),
            ("乍得", "乍得", "乍得共和国", "非洲"),
            ("贝宁", "贝宁", "贝宁共和国", "非洲"),
            ("多哥", "多哥", "多哥共和国", "非洲"),
            ("利比里亚", "利比里亚", "利比里亚共和国", "非洲"),
            ("塞拉利昂", "塞拉利昂", "塞拉利昂共和国", "非洲"),
            ("赤道几内亚", "赤道几内亚", "赤道几内亚共和国", "非洲"),
            ("毛里塔尼亚", "毛里塔尼亚", "毛里塔尼亚伊斯兰共和国", "非洲"),
            ("中非", "中非", "中非共和国", "非洲"),
            ("马拉维", "马拉维", "马拉维共和国", "非洲"),
            ("莱索托", "莱索托", "莱索托王国", "非洲"),
            ("斯威士兰", "埃斯瓦蒂尼", "埃斯瓦蒂尼王国", "非洲"),
            ("布基纳法索", "布基纳法索", "布基纳法索", "非洲"),
            ("佛得角", "佛得角", "佛得角共和国", "非洲"),
            ("冈比亚", "冈比亚", "冈比亚共和国", "非洲"),
            ("几内亚比绍", "几内亚比绍", "几内亚比绍共和国", "非洲"),
            ("科摩罗", "科摩罗", "科摩罗联盟", "非洲"),
            ("圣多美和普林西比", "圣普", "圣多美和普林西比民主共和国", "非洲"),
            ("西撒哈拉", "西撒哈拉", "撒哈拉阿拉伯民主共和国", "非洲"),
            ("索马里兰", "索马里兰", "索马里兰共和国", "非洲"),

            # 地区/出口/特殊标识补充（满足需求：欧标、东南亚、出口、右舵加入地区列表）
            ("东南亚", "东南亚", "东南亚地区", "亚洲"),
            ("欧标", "欧标", "欧洲标准/欧洲", "欧洲"),
            ("出口", "出口", "出口车型/海外出口", "海外"),
            ("右舵", "右舵", "右舵车型/海外右舵", "海外"),
        ]

        df = pd.DataFrame(country_data, columns=["国家/地区", "常用中文简称", "官方全称/别名", "所属大洲"])
        df.to_excel(file_path, sheet_name="地区列表", index=False, engine="openpyxl")
        return file_path
