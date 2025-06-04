# cit-portal-wrapper

**cit-portal-wrapper**は、CITポータルのPythonラッパーです。

出来ること:

- 掲示板情報の取得
- 成績の取得

## Installation

GitHubからpipでインストールできます。

```bash
pip install git+https://github.com/issa06/cit-portal-wrapper.git
```

## Usage

```python
import cit_portal_wrapper

# 掲示板情報の取得:
cit_portal_wrapper.get_noticeboard_json(user_id, password, full=False)

# 成績情報の取得:
cit_portal_wrapper.get_grades_json(user_id, password)
```

成績の取得例:

```json
{
    "year": "2022",
    "semester": "前期",
    "subject": "日本語表現法",
    "credits": "1.0",
    "evaluation": "Ｓ",
    "gpa_target": "○",
    "attendance": "",
    "teacher": "山田 太郎"
},
{
    "year": "2022",
    "semester": "前期",
    "subject": "初年次教育",
    "credits": "1.0",
    "evaluation": "合",
    "gpa_target": "",
    "attendance": "",
    "teacher": "田中 次郎"
},
```
