import feedparser
import openai
import os
import time
import re
import html
import requests 
import argparse  # 커맨드라인 인자 처리용
from urllib.parse import urlparse
from datetime import datetime
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from dotenv import load_dotenv
from dateutil import parser as date_parser
import notion_client


load_dotenv()

# 한국 주요 언론사 RSS 피드
RSS_FEEDS = {
    "한국경제": "https://www.hankyung.com/feed/economy",
    "매일경제": "https://www.mk.co.kr/rss/30200001/",
    "전자신문": "https://www.etnews.com/20/0101/list.xml",
    "조선비즈": "https://biz.chosun.com/rss/biz_total.xml",
    "서울경제": "https://www.sedaily.com/RSS/S01.xml",
}

def _clean_html(text: str) -> str:
    """HTML 태그/엔티티 제거"""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()

def collect_news_from_rss():
    """RSS로 뉴스 수집 (fallback / 또는 기본)"""
    print("📰 RSS로 뉴스 수집 시작...")
    all_articles = []

    for source, url in RSS_FEEDS.items():
        try:
            print(f"  → {source} 수집 중...")
            feed = feedparser.parse(url)

            count = 0
            for entry in feed.entries[:100]:
                title = _clean_html(entry.get("title", ""))
                summary = _clean_html(entry.get("summary", ""))[:500]

                article = {
                    "title": title,
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "summary": summary,
                    "source": source,
                    "originallink": entry.get("link", ""),  # RSS는 보통 link가 원문
                }
                if article["title"]:
                    all_articles.append(article)
                    count += 1

            print(f"     ✓ {count}개 수집")
            time.sleep(0.3)

        except Exception as e:
            print(f"     ✗ 오류: {e}")

    print(f"\n총 {len(all_articles)}개 기사 수집 완료!\n")
    return all_articles

def collect_news_from_naver(target_date=None):
    """
    네이버 뉴스 API로 뉴스 수집
    
    Args:
        target_date (str): 'YYYY-MM-DD' 형식 또는 None (오늘)
    """
    print("📰 네이버 뉴스 API로 수집 시작...")
    
    # 날짜 설정
    if target_date:
        try:
            target = datetime.strptime(target_date, "%Y-%m-%d")
            print(f"📅 수집 대상 날짜: {target.strftime('%Y년 %m월 %d일')}\n")
        except ValueError:
            print(f"❌ 잘못된 날짜 형식: {target_date} (YYYY-MM-DD 형식 필요)")
            return []
    else:
        target = datetime.now()
        print(f"📅 수집 대상 날짜: 오늘 ({target.strftime('%Y년 %m월 %d일')})\n")
    
    # 날짜 범위 설정 (해당 날짜 00:00 ~ 23:59)
    start_of_day = target.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = target.replace(hour=23, minute=59, second=59, microsecond=999999)

    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("❌ 네이버 API 키가 없습니다. RSS로 대체합니다.\n")
        return collect_news_from_rss()

    keywords = [
        "금융", "증시", "주식", "환율", "증권", "캐피탈", 
        "IT", "AI", "테크", "스테이블코인", "디지털자산",
        "삼성증권", "네이버", 
        "하나은행", "우리은행", "은행", "기업은행",
    ]

    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret
    }

    all_articles = []
    for keyword in keywords:
        try:
            print(f"  → '{keyword}' 검색 중...")

            params = {"query": keyword, "display": 100, "sort": "date"}
            response = requests.get(url, headers=headers, params=params, timeout=10)

            if response.status_code != 200:
                print(f"     ✗ 오류: {response.status_code}")
                continue

            data = response.json()
            count = 0
            for item in data.get("items", []):
                # ✅ 날짜 필터링 추가
                pub_date_str = item.get("pubDate", "")
                if pub_date_str:
                    try:
                        # 네이버 pubDate 형식: "Mon, 09 Jan 2026 14:30:00 +0900"
                        pub_date = date_parser.parse(pub_date_str)
                        
                        # 지정된 날짜가 아니면 스킵
                        if not (start_of_day <= pub_date <= end_of_day):
                            continue
                    except Exception as e:
                        # 날짜 파싱 실패하면 일단 포함
                        pass
                
                title = _clean_html(item.get("title", ""))
                description = _clean_html(item.get("description", ""))[:500]

                originallink = item.get("originallink") or ""
                link = item.get("link") or originallink

                source_domain = "네이버뉴스"
                try:
                    if originallink:
                        source_domain = urlparse(originallink).netloc or "네이버뉴스"
                except Exception:
                    pass

                article = {
                    "title": title,
                    "link": link,
                    "published": pub_date_str,
                    "summary": description,
                    "source": source_domain,
                    "originallink": originallink,
                }

                if article["title"]:
                    all_articles.append(article)
                    count += 1

            print(f"     ✓ {count}개 수집")
            time.sleep(0.12)

        except Exception as e:
            print(f"     ✗ 오류: {e}")

    print(f"\n총 {len(all_articles)}개 기사 수집 완료!\n")
    return all_articles


def dedup_by_url(articles):
    """URL 기준 1차 중복 제거 (네이버 키워드 루프 중복 방지)"""
    seen = set()
    out = []
    for a in articles:
        key = (a.get("originallink") or a.get("link") or "").strip()
        if not key:
            # url이 없으면 제목 기반으로라도 키 생성
            key = f"title::{a.get('title','')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out

def remove_duplicates_tfidf(articles, threshold=0.72):
    """TF-IDF 기반 2차 중복 제거 (title+summary)"""
    print("🔍 중복 기사 제거 중...")

    if not articles:
        return []

    docs = [(a.get("title","") + " " + a.get("summary","")).strip() for a in articles]

    try:
        vectorizer = TfidfVectorizer(min_df=1, ngram_range=(1, 2))
        tfidf_matrix = vectorizer.fit_transform(docs)
        sim = cosine_similarity(tfidf_matrix)

        keep = []
        removed = set()

        for i in range(len(articles)):
            if i in removed:
                continue
            keep.append(i)
            for j in range(i + 1, len(articles)):
                if sim[i][j] >= threshold:
                    removed.add(j)

        unique = [articles[i] for i in keep]
        print(f"  → {len(removed)}개 중복 제거")
        print(f"  → {len(unique)}개 고유 기사 남음\n")
        return unique

    except Exception as e:
        print(f"  ⚠️  중복 제거 오류: {e}")
        print(f"  → 원본 {len(articles)}개 그대로 사용\n")
        return articles

def summarize_news(articles):
    """AI 요약"""
    print("🤖 OpenAI GPT AI 요약 생성 중...\n")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "❌ 오류: OPENAI_API_KEY가 설정되지 않았습니다."

    client = openai.OpenAI(api_key=api_key)

    # 요약 입력을 title만 넣지 말고 summary도 같이
    # 너무 길어지면 비용/토큰 증가하니 80개 정도로 제한 권장
    selected = articles[:80]
    articles_text = "\n\n".join([
        f"[{a.get('source','')}] {a.get('title','')}\n- 요약: {a.get('summary','')}\n- 링크: {a.get('originallink') or a.get('link')}"
        for a in selected
    ])

    prompt = f"""다음은 오늘 수집된 한국 경제/IT 뉴스 기사 {len(selected)}개입니다.

{articles_text}

요구사항:
- 결과는 **A4 3페이지 이내(약 2000~2400자)**로 제한
- 중복 이슈는 반드시 통합 (같은 이슈 기사 여러 개면 1개로 묶어서)
- 섹션별 분량을 지켜 과도하게 길어지지 않게
- 각 섹션 제목은 h1으로

출력 형식:
1) 오늘의 핵심 5줄
2) 경제 TOP 10 (각 6~8줄)
3) IT/기술 TOP 10 (각 6~8줄)
4) 공통 트렌드 5~8줄
5) 내일 관전 포인트 5줄
6) 출처 링크(이슈별 대표 링크 1개씩)
7) 인사이트 추출
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "당신은 한국 경제/IT 뉴스 전문 에디터입니다. 객관적이고 간결한 데일리 브리핑을 작성합니다."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=3500,
            temperature=0.5
        )
        return response.choices[0].message.content

    except Exception as e:
        return f"❌ 오류: {e}"

def parse_inline_formatting(text):
    """텍스트에서 **bold**, Markdown 링크, 일반 URL 같은 인라인 서식을 파싱하여 Notion rich_text 객체 배열로 반환"""
    
    rich_text_elements = []
    last_idx = 0
    
    # Regex to find all three types of formatting
    # Group 'md_text': Markdown Link Text, Group 'md_url': Markdown Link URL
    # Group 'bold_text': Bold Text
    # Group 'raw_url': Raw URL
    # Pattern order is important: Markdown link should be matched before raw URL
    pattern = re.compile(
        r'\[(?P<md_text>[^\]]+?)\]\((?P<md_url>https?:\/\/[^\s\)]+)\)'  # Markdown link
        r'|\*\*(?P<bold_text>[^\*]+?)\*\*'                               # Bold text
        r'|(?P<raw_url>https?:\/\/[^\s]+)'                                # Raw URL
    )
    
    for match in pattern.finditer(text):
        start, end = match.span()
        
        # Add preceding plain text
        if start > last_idx:
            plain_text = text[last_idx:start]
            if plain_text:
                rich_text_elements.append({"type": "text", "text": {"content": plain_text}})
        
        # Process the matched part
        if match.group('md_text'): # It's a Markdown link
            md_text = match.group('md_text')
            md_url = match.group('md_url')
            rich_text_elements.append({
                "type": "text",
                "text": {"content": md_text, "link": {"url": md_url}},
                "annotations": {"bold": False} 
            })
        elif match.group('bold_text'): # It's bold text
            bold_text = match.group('bold_text')
            rich_text_elements.append({
                "type": "text",
                "text": {"content": bold_text},
                "annotations": {"bold": True}
            })
        elif match.group('raw_url'):  # It's a raw URL
            raw_url = match.group('raw_url')

            # ✅ 문장 끝에 붙는 구두점/닫는 괄호 제거
            # - 일반적으로 URL에 포함되지 않는 후행 문자들을 제거
            # - 필요하면 목록에 더 추가 가능
            raw_url = raw_url.rstrip(').,;:!?"\'”’》〉】]')

            rich_text_elements.append({
                "type": "text",
                "text": {"content": raw_url, "link": {"url": raw_url}},
                "annotations": {"bold": False}
            })
            
        last_idx = end
    
    # Add any remaining plain text at the end
    if last_idx < len(text):
        plain_text = text[last_idx:]
        if plain_text:
            rich_text_elements.append({"type": "text", "text": {"content": plain_text}})
            
    return rich_text_elements

def add_to_notion(title, content, report_date_str):
    """Notion DB에 요약 리포트 추가"""
    print("📝 Notion에 리포트 등록 중...")

    api_key = os.getenv("NOTION_API_KEY")
    database_id = os.getenv("NOTION_DATABASE_ID")

    if not api_key or not database_id:
        print("❌ Notion API 키 또는 데이터베이스 ID가 없습니다.")
        print("   .env 파일에 NOTION_API_KEY와 NOTION_DATABASE_ID를 설정하세요.\n")
        return

    try:
        notion = notion_client.Client(auth=api_key)

        children_blocks = []
        lines = content.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped_line = line.strip()

            if not stripped_line:
                i += 1
                continue

            # --- 블록 레벨 요소 처리 ---

            # 제목 (Headings)
            if stripped_line.startswith('# '):
                text_content = stripped_line[2:]
                block = {"object": "block", "type": "heading_1", "heading_1": {"rich_text": parse_inline_formatting(text_content)}}
                children_blocks.append(block)
                i += 1
                continue
            elif stripped_line.startswith('## '):
                text_content = stripped_line[3:]
                block = {"object": "block", "type": "heading_2", "heading_2": {"rich_text": parse_inline_formatting(text_content)}}
                children_blocks.append(block)
                i += 1
                continue
            elif stripped_line.startswith('### '):
                text_content = stripped_line[4:]
                block = {"object": "block", "type": "heading_3", "heading_3": {"rich_text": parse_inline_formatting(text_content)}}
                children_blocks.append(block)
                i += 1
                continue

            # 목록 그룹 처리 (Process a whole list at once)
            is_numbered = re.match(r'^\d+[\.\)]\s', stripped_line)
            is_bulleted = stripped_line.startswith(('- ', '* '))
            if is_numbered or is_bulleted:
                list_type_to_process = 'numbered' if is_numbered else 'bulleted'
                
                # Loop as long as we are in the same type of list
                while i < len(lines):
                    current_line_stripped = lines[i].strip()
                    if not current_line_stripped:
                        # empty line breaks the list
                        break 
                    
                    is_current_line_numbered = re.match(r'^\d+[\.\)]\s', current_line_stripped)
                    is_current_line_bulleted = current_line_stripped.startswith(('- ', '* '))

                    # Break if list type changes or it's not a list item
                    if (list_type_to_process == 'numbered' and not is_current_line_numbered) or \
                       (list_type_to_process == 'bulleted' and not is_current_line_bulleted) or \
                        current_line_stripped.startswith('#'):
                        break

                    # It's a valid item of the current list. Process it.
                    if is_current_line_numbered:
                        text_content = re.sub(r'^\d+[\.\)]\s', '', current_line_stripped)
                        block_type = 'numbered_list_item'
                    else:
                        text_content = current_line_stripped[2:]
                        block_type = 'bulleted_list_item'

                    # Find multi-line content for this item
                    item_content_end_index = i + 1
                    while item_content_end_index < len(lines):
                        next_line = lines[item_content_end_index]
                        next_line_stripped = next_line.strip()
                        # Stop if next line is a new list/block type or empty
                        if not next_line_stripped or next_line_stripped.startswith(('#', '- ', '* ')) or re.match(r'^\d+[\.\)]\s', next_line_stripped):
                            break
                        text_content += '\n' + next_line
                        item_content_end_index += 1

                    # Create and append the list item block
                    rich_text = parse_inline_formatting(text_content)
                    block = {"object": "block", "type": block_type, block_type: {"rich_text": rich_text}}
                    children_blocks.append(block)

                    # Move master index 'i' to the next item
                    i = item_content_end_index
                
                continue # Finished processing the list, restart main while loop

            # 일반 문단 (Paragraphs) - Fallback
            text_content = line
            i += 1
            # Consume subsequent lines until a new block starts
            while i < len(lines):
                next_line = lines[i]
                next_line_stripped = next_line.strip()
                if not next_line_stripped or \
                    next_line_stripped.startswith(('#', '- ', '* ')) or \
                    re.match(r'^\d+[\.\)]\s', next_line_stripped):
                    break
                text_content += '\n' + next_line
                i += 1
            
            block = {"object": "block", "type": "paragraph", "paragraph": {"rich_text": parse_inline_formatting(text_content)}}
            children_blocks.append(block)

        # --- Notion 페이지 생성 ---
        TITLE_PROPERTY_NAME = "이름"
        DATE_PROPERTY_NAME = "날짜"

        new_page_data = {
            "parent": {"database_id": database_id},
            "properties": {
                TITLE_PROPERTY_NAME: {"title": [{"text": {"content": title}}]},
                DATE_PROPERTY_NAME: {"date": {"start": report_date_str}}
            },
            "children": children_blocks
        }

        notion.pages.create(**new_page_data)
        print("✅ Notion 등록 완료!\n")

    except Exception as e:
        err_msg = str(e).lower()
        if "property" in err_msg and ("does not exist" in err_msg or "unrecognized property" in err_msg):
            print(f"❌ Notion 등록 오류: 데이터베이스에 필요한 속성이 없거나 이름이 다릅니다.")
            print(f"   main.py 파일의 'add_to_notion' 함수에서 속성 이름을 확인하고,")
            print(f"   사용자 Notion DB의 실제 속성 이름으로 TITLE_PROPERTY_NAME과 DATE_PROPERTY_NAME을 수정해주세요.")
            print(f"   (현재 설정: 제목='{TITLE_PROPERTY_NAME}', 날짜='{DATE_PROPERTY_NAME}')\n")
        else:
            print(f"❌ Notion 등록 오류: {e}\n")


def save_report(summary, articles_count, target_date=None):
    os.makedirs("reports", exist_ok=True)
    
    if target_date:
        date_obj = datetime.strptime(target_date, "%Y-%m-%d")
        today = date_obj.strftime("%Y%m%d")
        display_date = date_obj.strftime('%Y년 %m월 %d일')
    else:
        today = datetime.now().strftime("%Y%m%d")
        display_date = datetime.now().strftime('%Y년 %m월 %d일')
    
    filename = f"reports/daily_report_{today}.txt"

    report = f"""

{summary}

{"="*70}
"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"✅ 저장 완료: {filename}\n")
    return filename

def main():
    # 커맨드라인 인자 파싱
    parser = argparse.ArgumentParser(description='경제/IT 뉴스 요약 서비스')
    parser.add_argument(
        '--date', '-d',
        type=str,
        default=None,
        help='수집할 날짜 (YYYY-MM-DD 형식, 예: 2026-01-10). 미지정시 오늘'
    )
    args = parser.parse_args()
    
    print("\n" + "="*70)
    print("🚀 경제/IT 뉴스 요약 서비스 시작 (OpenAI + Naver/RSS)")
    print("="*70 + "\n")

    # ✅ 날짜 파라미터 전달
    articles = collect_news_from_naver(target_date=args.date)

    if not articles:
        print("❌ 수집된 기사가 없습니다.")
        return

    articles = dedup_by_url(articles)
    unique_articles = remove_duplicates_tfidf(articles, threshold=0.72)

    summary = summarize_news(unique_articles)
    filename = save_report(summary, len(unique_articles), target_date=args.date)

    # Notion에 등록
    # 날짜가 지정되지 않았을 경우 오늘 날짜로 설정
    if args.date:
        report_date = datetime.strptime(args.date, "%Y-%m-%d")
    else:
        # report 파일 저장시 사용된 날짜와 동일하게 오늘 날짜 사용
        report_date = datetime.now()

    report_title = f"{report_date.strftime('%Y년 %m월 %d일')} 뉴스 브리핑"
    add_to_notion(report_title, summary, report_date.strftime("%Y-%m-%d"))

    print("="*70)
    print("✨ 완료! 리포트를 확인하세요:")
    print(f"   📄 {filename}")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()