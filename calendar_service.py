import base64
import calendar
import json
import subprocess
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Dict, Iterable, List


SOLAR_TERMS = (
    "小寒", "大寒", "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
    "立夏", "小满", "芒种", "夏至", "小暑", "大暑", "立秋", "处暑",
    "白露", "秋分", "寒露", "霜降", "立冬", "小雪", "大雪", "冬至",
)
SOLAR_TERM_MINUTES = (
    0, 21208, 42467, 63836, 85337, 107014, 128867, 150921,
    173149, 195551, 218072, 240693, 263343, 285989, 308563, 331033,
    353350, 375494, 397447, 419210, 440795, 462224, 483532, 504758,
)

LUNAR_MONTHS = ("", "正月", "二月", "三月", "四月", "五月", "六月",
                "七月", "八月", "九月", "十月", "冬月", "腊月")
LUNAR_DAYS = ("", "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
              "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
              "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十")
LUNAR_FESTIVALS = {
    (1, 1): "春节", (1, 15): "元宵", (2, 2): "龙抬头", (5, 5): "端午",
    (7, 7): "七夕", (7, 15): "中元", (8, 15): "中秋", (9, 9): "重阳",
    (12, 8): "腊八", (12, 23): "小年",
}

# 国办发明电〔2025〕7号：2026年部分节假日安排。
HOLIDAYS_2026: Dict[str, Dict[str, str]] = {}
for start, end, name in (
    ("2026-01-01", "2026-01-03", "元旦"),
    ("2026-02-15", "2026-02-23", "春节"),
    ("2026-04-04", "2026-04-06", "清明"),
    ("2026-05-01", "2026-05-05", "劳动节"),
    ("2026-06-19", "2026-06-21", "端午"),
    ("2026-09-25", "2026-09-27", "中秋"),
    ("2026-10-01", "2026-10-07", "国庆"),
):
    cursor = date.fromisoformat(start)
    finish = date.fromisoformat(end)
    while cursor <= finish:
        HOLIDAYS_2026[cursor.isoformat()] = {"type": "holiday", "name": name}
        cursor += timedelta(days=1)
for workday, name in (
    ("2026-01-04", "元旦调休"), ("2026-02-14", "春节调休"),
    ("2026-02-28", "春节调休"), ("2026-05-09", "劳动节调休"),
    ("2026-09-20", "国庆调休"), ("2026-10-10", "国庆调休"),
):
    HOLIDAYS_2026[workday] = {"type": "workday", "name": name}


def month_grid(year: int, month: int) -> List[date]:
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    while len(weeks) < 6:
        last = weeks[-1][-1]
        weeks.append([last + timedelta(days=i) for i in range(1, 8)])
    return [day for week in weeks for day in week]


@lru_cache(maxsize=36)
def lunar_month(year: int, month: int) -> Dict[str, Dict]:
    days = month_grid(year, month)
    raw = _windows_lunar(days)
    result = {}
    for day in days:
        key = day.isoformat()
        terms = solar_terms_for_year(day.year)
        lunar = raw.get(key, {})
        lunar_month_num = lunar.get("month", 0)
        lunar_day_num = lunar.get("day", 0)
        label = ""
        festival = ""
        if lunar_month_num and lunar_day_num:
            festival = LUNAR_FESTIVALS.get((lunar_month_num, lunar_day_num), "")
            if festival:
                label = festival
            elif lunar_day_num == 1:
                label = ("闰" if lunar.get("leap") else "") + LUNAR_MONTHS[lunar_month_num]
            else:
                label = LUNAR_DAYS[lunar_day_num]
        term = terms.get(key, "")
        if term:
            label = term
        result[key] = {
            **lunar, "label": label, "festival": festival, "solar_term": term,
            "holiday": HOLIDAYS_2026.get(key),
        }
    return result


def _windows_lunar(days: Iterable[date]) -> Dict[str, Dict]:
    literals = ",".join("'%s'" % day.isoformat() for day in days)
    script = f"""
$ErrorActionPreference='Stop'
$cal=New-Object System.Globalization.ChineseLunisolarCalendar
$dates=@({literals})
$out=@()
foreach($s in $dates){{
  $d=[datetime]::ParseExact($s,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture)
  $y=$cal.GetYear($d); $m=$cal.GetMonth($d); $day=$cal.GetDayOfMonth($d)
  $leap=$cal.GetLeapMonth($y); $isLeap=$false
  if($leap -gt 0){{
    if($m -eq $leap){{$isLeap=$true; $m=$m-1}} elseif($m -gt $leap){{$m=$m-1}}
  }}
  $out += [pscustomobject]@{{date=$s;year=$y;month=$m;day=$day;leap=$isLeap}}
}}
$out | ConvertTo-Json -Compress
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            return {}
        payload = json.loads(completed.stdout.decode("utf-8-sig"))
        if isinstance(payload, dict):
            payload = [payload]
        return {item["date"]: item for item in payload}
    except (OSError, ValueError, subprocess.SubprocessError, UnicodeError):
        return {}


@lru_cache(maxsize=20)
def solar_terms_for_year(year: int) -> Dict[str, str]:
    base = datetime(1900, 1, 6, 2, 5)
    result = {}
    for index, minutes in enumerate(SOLAR_TERM_MINUTES):
        moment = base + timedelta(milliseconds=31556925974.7 * (year - 1900) + minutes * 60_000)
        result[moment.date().isoformat()] = SOLAR_TERMS[index]
    return result
