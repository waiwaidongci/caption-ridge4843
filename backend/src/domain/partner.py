"""合作方工时导出：按日、周或整段汇总已完工工单，并防止小样本日期段被反推。

口径：
- 只统计已填实耗分钟的完工工单，日期范围可空，粒度为按日、按周或整段。
- 只有一两单的日期段不展示精确实耗，隐藏处在表内注明原因。
- 合计只有在无法反推被隐藏段时才展示精确值。

防反推原理：把批次内每个有完工工单的日期看作一个原子，每个已展示的精确小计
（含合计）都是原子上的 0/1 指示向量。若某个一两单日期段的指示向量落在全部
已发表格向量的张成空间内，合作方就能用已发数字加减推出该段实耗。发布前用
行最简阶梯基（精确有理数）判定这一包含关系，命中即拒绝发布。

敏感段的完备性：任意连续日期段工单数不超过二时，它要么是一个原子（一两单），
要么是两个相邻原子（各一单）；三个及以上原子至少有三单，无需保护。
"""

from datetime import date
from fractions import Fraction
from hashlib import sha256
from math import fsum

GRANULARITIES = ("day", "week", "period")
MIN_VISIBLE = 3  # 日期段至少三单才展示精确实耗


def normalize_range(start, end):
    """校验并规范化可选日期范围，返回 (start_iso|None, end_iso|None)。"""

    def parse(value, label):
        if value in (None, ""):
            return None
        try:
            return date.fromisoformat(str(value).strip()).isoformat()
        except ValueError:
            raise ValueError(f"{label}格式不正确，应为 YYYY-MM-DD") from None

    start, end = parse(start, "起始日期"), parse(end, "结束日期")
    if start and end and start > end:
        raise ValueError("起始日期不能晚于结束日期")
    return start, end


def fingerprint(dataset_id, granularity, start, end):
    """同一份表（同批次、同粒度、同日期范围）的稳定标识，用于发布去重。"""
    raw = f"{dataset_id}|{granularity}|{start or ''}|{end or ''}"
    return sha256(raw.encode()).hexdigest()


def dataset_atoms(rows):
    """按日期汇总已完工工单，返回 [(day_iso, count, minutes)]，仅含有单的日期，升序。"""
    days = {}
    for row in rows:
        minutes = row.get("actual_minutes")
        if minutes is None:
            continue
        count, total = days.get(row["job_date"], (0, 0.0))
        days[row["job_date"]] = (count + 1, total + minutes)
    return [(day, count, total) for day, (count, total) in sorted(days.items())]


def sensitive_spans(atoms):
    """需要保护的日期段（原子下标元组）：一两单的单日，以及相邻两个各一单的日子。"""
    spans = []
    for index, (_, count, _) in enumerate(atoms):
        if count < MIN_VISIBLE:
            spans.append((index,))
        if index + 1 < len(atoms) and count == 1 and atoms[index + 1][1] == 1:
            spans.append((index, index + 1))
    return spans


class Basis:
    """已展示小计覆盖日期的行最简阶梯基（精确有理数），用于张成判定。"""

    def __init__(self):
        self.rows = {}  # pivot -> {column: Fraction}

    @staticmethod
    def _combine(target, source, scale):
        merged = dict(target)
        for column, value in source.items():
            updated = merged.get(column, Fraction(0)) + scale * value
            if updated:
                merged[column] = updated
            else:
                merged.pop(column, None)
        return merged

    def _reduce(self, vector):
        current = {column: Fraction(value) for column, value in vector.items() if value}
        for pivot in sorted(self.rows):
            coeff = current.get(pivot)
            if coeff:
                current = self._combine(current, self.rows[pivot], -coeff)
        return current

    def add(self, vector):
        remainder = self._reduce(vector)
        if not remainder:
            return
        pivot = min(remainder)
        scale = remainder[pivot]
        if scale != 1:
            remainder = {column: value / scale for column, value in remainder.items()}
        for existing, row in list(self.rows.items()):
            coeff = row.get(pivot)
            if coeff:
                self.rows[existing] = self._combine(row, remainder, -coeff)
        self.rows[pivot] = remainder

    def contains(self, vector):
        return not self._reduce(vector)


def find_violations(atoms, cells):
    """cells 为已展示小计覆盖的日期列表；返回可被反推的敏感日期段（原子下标元组）。"""
    index_of = {day: index for index, (day, _, _) in enumerate(atoms)}
    basis = Basis()
    for cell in cells:
        basis.add({index_of[day]: 1 for day in cell})
    return [span for span in sensitive_spans(atoms) if basis.contains({index: 1 for index in span})]


def describe_violations(atoms, spans, limit=3):
    parts = []
    for span in spans[:limit]:
        first, last = atoms[span[0]][0], atoms[span[-1]][0]
        count = sum(atoms[index][1] for index in span)
        label = first if first == last else f"{first} 至 {last}"
        parts.append(f"{label}（{count} 单）")
    return "、".join(parts) + (" 等" if len(spans) > limit else "")


def _bucket(day, granularity):
    if granularity == "day":
        return (day,)
    if granularity == "week":
        iso = date.fromisoformat(day).isocalendar()
        return (iso[0], iso[1])
    return ("period",)


def _label(key, days, granularity):
    if granularity == "day":
        return days[0]
    if granularity == "week":
        return f"{key[0]} 年第 {key[1]:02d} 周（{days[0][5:]} 至 {days[-1][5:]}）"
    return f"整段（{days[0]} 至 {days[-1]}）"


def build_table(rows, granularity, start=None, end=None):
    """按粒度与可选范围出表；不足三单的段隐藏实耗并注明原因，合计按反推风险取舍。"""
    if granularity not in GRANULARITIES:
        raise ValueError("出表粒度仅支持按日、按周或整段")
    start, end = normalize_range(start, end)
    atoms = dataset_atoms(rows)
    if start:
        atoms = [atom for atom in atoms if atom[0] >= start]
    if end:
        atoms = [atom for atom in atoms if atom[0] <= end]
    if not atoms:
        raise ValueError("该日期范围内没有已完工讲座")

    buckets = {}
    for day, count, minutes in atoms:
        bucket = buckets.setdefault(_bucket(day, granularity), {"days": [], "count": 0, "minutes": []})
        bucket["days"].append(day)
        bucket["count"] += count
        bucket["minutes"].append(minutes)

    table_rows, cells, hidden = [], [], 0
    for key in sorted(buckets):
        bucket = buckets[key]
        visible = bucket["count"] >= MIN_VISIBLE
        if visible:
            cells.append(bucket["days"])
            minutes, reason = round(fsum(bucket["minutes"]), 2), None
        else:
            hidden += 1
            minutes = None
            reason = f"该段仅 {bucket['count']} 单，不足 {MIN_VISIBLE} 单的日期段不展示实耗，防止小样本反推"
        table_rows.append({"label": _label(key, bucket["days"], granularity), "dates": bucket["days"],
                           "count": bucket["count"], "minutes": minutes, "reason": reason})

    total_days = [day for day, _, _ in atoms]
    total = {"label": "合计", "dates": total_days, "count": sum(count for _, count, _ in atoms),
             "minutes": round(fsum(minutes for _, _, minutes in atoms), 2), "reason": None}
    if find_violations(atoms, cells + [total_days]):
        hidden += 1
        total["minutes"] = None
        total["reason"] = "展示精确合计将可反推被隐藏段的实耗，故合计一并隐藏"
    else:
        cells.append(total_days)

    return {"granularity": granularity, "start": atoms[0][0], "end": atoms[-1][0],
            "rows": table_rows, "total": total, "cells": cells,
            "order_count": total["count"], "hidden": hidden}
