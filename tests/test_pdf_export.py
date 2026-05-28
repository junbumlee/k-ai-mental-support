import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_node(script: str) -> str:
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_export_helper_builds_readable_pdf_html_from_saved_entries():
    output = run_node(
        """
        const assert = require('assert');
        const exporter = require('./static/export.js');
        const html = exporter.buildEntriesPdfHtml([
          {
            createdAt: '2026-05-28T06:00:00.000Z',
            entry: {
              category: '팀원 관리',
              situation: '팀원이 회의에서 침묵했다\\n후속 질문도 없었다',
              thought: '내가 팀을 못 이끈다 <script>',
              reframe: '질문 방식이 맞지 않았을 수 있다'
            },
            feedback: {
              empathy: '회의의 침묵이 무겁게 느껴졌겠어요.',
              distortions: ['개인화', '파국화'],
              reframe: '침묵이 곧 리더십 실패라는 근거가 충분할까요?',
              question: '다음 회의에서 질문을 하나만 바꿔보세요.'
            }
          }
        ], {
          title: '테스트 기록',
          filenamePrefix: 'worrydoll',
          exportedAt: '2026-05-28T06:30:00.000Z'
        });
        assert(html.includes('<h1>테스트 기록</h1>'));
        assert(html.includes('<title>worrydoll-20260528</title>'));
        assert(html.includes('기록 수: 1'));
        assert(html.includes('<p>팀원이 회의에서 침묵했다</p>'));
        assert(html.includes('<p>후속 질문도 없었다</p>'));
        assert(html.includes('&lt;script&gt;'));
        assert(html.includes('<h3>생각의 습관</h3>'));
        assert(html.includes('개인화, 파국화'));
        assert(html.includes('@page'));
        console.log('ok');
        """
    )

    assert output == "ok"


def test_export_helper_handles_empty_entries_and_pdf_filename():
    output = run_node(
        """
        const assert = require('assert');
        const exporter = require('./static/export.js');
        const html = exporter.buildEntriesPdfHtml([], {
          title: '빈 기록',
          exportedAt: '2026-05-28T06:30:00.000Z'
        });
        assert(html.includes('<h1>빈 기록</h1>'));
        assert(html.includes('기록 수: 0'));
        assert(html.includes('아직 저장된 기록이 없습니다.'));
        assert.strictEqual(
          exporter.makeExportFilename('worrydoll', '2026-05-28T06:30:00.000Z'),
          'worrydoll-20260528.pdf'
        );
        console.log('ok');
        """
    )

    assert output == "ok"


def test_export_helper_writes_print_window_without_autoprint():
    output = run_node(
        """
        const assert = require('assert');
        const exporter = require('./static/export.js');
        let written = '';
        const fakeWindow = {
          document: {
            readyState: 'complete',
            open() {},
            write(html) { written = html; },
            close() {}
          },
          focus() { throw new Error('should not focus when autoPrint is false'); },
          print() { throw new Error('should not print when autoPrint is false'); }
        };
        const ok = exporter.openPdfPrintWindow([], {
          title: '테스트',
          autoPrint: false,
          openWindow: () => fakeWindow
        });
        assert.strictEqual(ok, true);
        assert(written.includes('<h1>테스트</h1>'));
        console.log('ok');
        """
    )

    assert output == "ok"


def test_templates_load_export_helper_before_page_script_and_show_pdf_label():
    index_html = (ROOT / "templates" / "index.html").read_text()
    leaders_html = (ROOT / "templates" / "leaders.html").read_text()

    assert index_html.index("/static/export.js") < index_html.index("/static/app.js")
    assert leaders_html.index("/static/export.js") < leaders_html.index("/static/leaders.js")
    assert 'id="export-entries"' in index_html
    assert 'id="export-entries"' in leaders_html
    assert "PDF 내보내기" in index_html
    assert "PDF 내보내기" in leaders_html
