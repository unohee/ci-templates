#!/usr/bin/env python3
"""
Fake Data Detector - 가짜 데이터 패턴 탐지기

ML 학습 코드에서 가짜/무의미한 데이터 생성 패턴을 탐지합니다.

탐지 패턴:
1. np.random으로 피처 생성 (학습 데이터 오염)
2. 매직 넘버 (하드코딩된 임계값)
3. 가짜 성공 메시지
4. 예외 은폐 패턴

사용법:
    python scripts/fake_data_detector.py [파일/디렉토리...]
    python scripts/fake_data_detector.py src/ --ci
    python scripts/fake_data_detector.py . --strict

환경 변수:
    FAKE_DATA_FEATURE_PATTERNS: 피처 변수 패턴 (콤마 구분)
    FAKE_DATA_EXCLUDE_PATHS: 제외 경로 (콤마 구분)

Created: 2026-01-21
Repository: https://github.com/unohee/ci-templates
"""

import ast
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class Issue:
    """탐지된 이슈"""
    severity: str  # CRITICAL, WARNING, INFO
    file: str
    line: int
    message: str
    pattern: str
    suggestion: Optional[str] = None


@dataclass
class DetectionResult:
    """탐지 결과"""
    issues: List[Issue] = field(default_factory=list)
    files_scanned: int = 0

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "CRITICAL")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "WARNING")

    @property
    def bs_score(self) -> float:
        """BS 지수 계산: CRITICAL×10 + WARNING×3 + INFO×1"""
        weights = {"CRITICAL": 10, "WARNING": 3, "INFO": 1}
        total = sum(weights.get(i.severity, 1) for i in self.issues)
        return total / max(self.files_scanned, 1)

    @property
    def passed(self) -> bool:
        return self.critical_count == 0


class FakeDataDetector(ast.NodeVisitor):
    """AST 기반 가짜 데이터 패턴 탐지기"""

    # 가짜 데이터 생성 패턴
    #
    # These are the names this detector looks for, held as dict keys. `cxt bs` reads the
    # string literals as calls and reports seven CRITICAL fake_data findings against the
    # detector itself — a scanner cannot tell naming a pattern from using one. The
    # suppression is scoped to that one category so every other smell still surfaces
    # (book.md Art. II: disagree with evidence in writing, or fix it).
    FAKE_DATA_PATTERNS = {
        # np.random으로 피처 생성
        "np.random.rand": "CRITICAL",  # cxt-ignore: fake_data
        "np.random.randn": "CRITICAL",  # cxt-ignore: fake_data
        "np.random.random": "CRITICAL",  # cxt-ignore: fake_data
        "np.random.uniform": "CRITICAL",  # cxt-ignore: fake_data
        "np.random.normal": "CRITICAL",  # cxt-ignore: fake_data
        "np.random.choice": "WARNING",  # 샘플링은 WARNING  # cxt-ignore: fake_data
        "random.random": "CRITICAL",  # cxt-ignore: fake_data
        "random.uniform": "CRITICAL",  # cxt-ignore: fake_data
        # faker 라이브러리
        "faker.Faker": "WARNING",  # cxt-ignore: fake_data
    }

    # 허용된 컨텍스트 (테스트, 시드 설정 등)
    ALLOWED_CONTEXTS = [
        "test_",
        "mock_",
        "seed",
        "random_state",
        "shuffle",
        "sample",
    ]

    # 피처 변수 패턴 (환경 변수로 설정 가능)
    FEATURE_PATTERNS = os.environ.get(
        "FAKE_DATA_FEATURE_PATTERNS",
        "feature,program,arbitrage"
    ).split(",")

    def __init__(self, source: str, filename: str):
        self.source = source
        self.filename = filename
        self.lines = source.split("\n")
        self.issues: List[Issue] = []
        self.current_function: Optional[str] = None
        self.current_class: Optional[str] = None

    def detect(self) -> List[Issue]:
        """전체 탐지 실행"""
        try:
            tree = ast.parse(self.source)
            self.visit(tree)
        except SyntaxError:
            pass  # 구문 오류는 무시 (다른 도구가 처리)

        # 텍스트 패턴 탐지
        self._detect_text_patterns()

        return self.issues

    def visit_FunctionDef(self, node):
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = None

    def visit_AsyncFunctionDef(self, node):
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = None

    def visit_ClassDef(self, node):
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = None

    def visit_Call(self, node):
        """함수 호출 탐지"""
        call_name = self._get_call_name(node)

        # np.random 패턴 탐지
        for pattern, severity in self.FAKE_DATA_PATTERNS.items():
            if pattern in call_name:
                if not self._is_allowed_context():
                    self.issues.append(Issue(
                        severity=severity,
                        file=self.filename,
                        line=node.lineno,
                        message=f"가짜 데이터 생성 패턴: {call_name}",
                        pattern=pattern,
                        suggestion="실제 API 데이터 또는 검증된 데이터 소스 사용"
                    ))

        self.generic_visit(node)

    def visit_Assign(self, node):
        """할당문 탐지 - 피처 생성 매직 넘버"""
        line = self._get_source_line(node.lineno)

        # 피처 할당에서 하드코딩된 비율 탐지
        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id

                # 피처 변수에 np.random 사용
                if any(kw in var_name.lower() for kw in self.FEATURE_PATTERNS):
                    if "np.random" in line or "random." in line:
                        self.issues.append(Issue(
                            severity="CRITICAL",
                            file=self.filename,
                            line=node.lineno,
                            message=f"피처 '{var_name}'에 랜덤 데이터 할당",
                            pattern="feature_random_assignment",
                            suggestion="실제 API 데이터 사용 또는 피처 제거"
                        ))

                    # 매직 넘버 (0.6 * something 패턴)
                    if re.search(r"=\s*\d+\.\d+\s*\*", line):
                        self.issues.append(Issue(
                            severity="WARNING",
                            file=self.filename,
                            line=node.lineno,
                            message=f"피처 '{var_name}'에 매직 넘버 사용",
                            pattern="magic_number",
                            suggestion="상수로 정의하거나 설정 파일에서 로드"
                        ))

        self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        """예외 은폐 탐지"""
        if not node.body or all(isinstance(n, ast.Pass) for n in node.body):
            self.issues.append(Issue(
                severity="CRITICAL",
                file=self.filename,
                line=node.lineno,
                message="예외 은폐 (except: pass)",
                pattern="exception_hiding",
                suggestion="적절한 에러 처리 또는 로깅 추가"
            ))

        self.generic_visit(node)

    def _detect_text_patterns(self):
        """텍스트 기반 패턴 탐지"""
        for i, line in enumerate(self.lines, 1):
            # 주석 제외
            code_line = line.split("#")[0]

            # 가짜 성공 메시지 (한국어/영어)
            if re.search(r'print\s*\(\s*["\'].*(?:완료|success|done)', line, re.IGNORECASE):
                self.issues.append(Issue(
                    severity="WARNING",
                    file=self.filename,
                    line=i,
                    message="근거 없는 완료 메시지",
                    pattern="fake_success",
                    suggestion="실제 검증 결과 기반 메시지로 변경"
                ))

            # TODO + pass 패턴
            if "TODO" in line and "pass" in code_line:
                self.issues.append(Issue(
                    severity="WARNING",
                    file=self.filename,
                    line=i,
                    message="TODO + pass 미완성 코드",
                    pattern="todo_pass",
                    suggestion="구현 완료 또는 NotImplementedError 사용"
                ))

    def _get_call_name(self, node) -> str:
        """호출 이름 추출"""
        parts = []
        current = node.func

        while True:
            if isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            elif isinstance(current, ast.Name):
                parts.append(current.id)
                break
            else:
                break

        return ".".join(reversed(parts))

    def _get_source_line(self, lineno: int) -> str:
        """소스 라인 추출"""
        if 0 < lineno <= len(self.lines):
            return self.lines[lineno - 1]
        return ""

    def _is_allowed_context(self) -> bool:
        """허용된 컨텍스트인지 확인"""
        context = f"{self.current_class or ''}.{self.current_function or ''}"
        return any(allowed in context.lower() for allowed in self.ALLOWED_CONTEXTS)


def scan_file(filepath: Path) -> List[Issue]:
    """파일 스캔"""
    try:
        source = filepath.read_text(encoding="utf-8")
        detector = FakeDataDetector(source, str(filepath))
        return detector.detect()
    except Exception as e:
        return [Issue(
            severity="WARNING",
            file=str(filepath),
            line=0,
            message=f"파일 읽기 오류: {e}",
            pattern="read_error"
        )]


def scan_directory(dirpath: Path, exclude_patterns: List[str] = None) -> DetectionResult:
    """디렉토리 스캔"""
    # 환경 변수에서 제외 패턴 로드
    env_excludes = os.environ.get("FAKE_DATA_EXCLUDE_PATHS", "").split(",")
    env_excludes = [e.strip() for e in env_excludes if e.strip()]

    exclude_patterns = exclude_patterns or []
    exclude_patterns.extend(env_excludes)
    exclude_patterns.extend([
        "__pycache__",
        ".git",
        "trash",
        "archive",
        ".venv",
        "venv",
        "node_modules",
    ])

    result = DetectionResult()

    for py_file in dirpath.rglob("*.py"):
        # 제외 패턴 체크
        if any(excl in str(py_file) for excl in exclude_patterns):
            continue

        issues = scan_file(py_file)
        result.issues.extend(issues)
        result.files_scanned += 1

    return result


def format_report(result: DetectionResult) -> str:
    """리포트 포매팅"""
    lines = [
        "=" * 70,
        "Fake Data Detector Report",
        "=" * 70,
        f"Files scanned: {result.files_scanned}",
        f"Critical issues: {result.critical_count}",
        f"Warning issues: {result.warning_count}",
        f"BS Score: {result.bs_score:.2f} / 5.0",
        f"Status: {'PASS' if result.passed else 'FAIL'}",
        "=" * 70,
    ]

    if result.issues:
        lines.append("\nIssues found:\n")

        # 심각도별 정렬
        severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        sorted_issues = sorted(result.issues, key=lambda x: severity_order.get(x.severity, 9))

        for issue in sorted_issues:
            emoji = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "🔵"}.get(issue.severity, "⚪")
            lines.append(f"{emoji} [{issue.severity}] {issue.file}:{issue.line}")
            lines.append(f"   {issue.message}")
            if issue.suggestion:
                lines.append(f"   💡 {issue.suggestion}")
            lines.append("")
    else:
        lines.append("\nNo issues found!")

    return "\n".join(lines)


def main():
    """메인 실행"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Fake Data Detector - ML 코드에서 가짜 데이터 패턴 탐지",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  %(prog)s src/              # src/ 디렉토리 스캔
  %(prog)s . --ci            # CI 모드 (GitHub Actions 형식)
  %(prog)s . --strict        # WARNING도 실패로 처리
  %(prog)s . --json          # JSON 출력

환경 변수:
  FAKE_DATA_FEATURE_PATTERNS  피처 변수 패턴 (콤마 구분, 기본: feature,program,arbitrage)
  FAKE_DATA_EXCLUDE_PATHS     제외 경로 (콤마 구분)
        """
    )
    parser.add_argument("paths", nargs="*", default=["."], help="파일 또는 디렉토리 경로")
    parser.add_argument("--strict", action="store_true", help="WARNING도 실패로 처리")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    parser.add_argument("--ci", action="store_true", help="CI 모드 (GitHub Actions 형식)")
    args = parser.parse_args()

    result = DetectionResult()

    for path_str in args.paths:
        path = Path(path_str)
        if path.is_file():
            issues = scan_file(path)
            result.issues.extend(issues)
            result.files_scanned += 1
        elif path.is_dir():
            dir_result = scan_directory(path)
            result.issues.extend(dir_result.issues)
            result.files_scanned += dir_result.files_scanned

    # 출력
    if args.json:
        import json
        output = {
            "files_scanned": result.files_scanned,
            "critical_count": result.critical_count,
            "warning_count": result.warning_count,
            "bs_score": result.bs_score,
            "passed": result.passed,
            "issues": [
                {
                    "severity": i.severity,
                    "file": i.file,
                    "line": i.line,
                    "message": i.message,
                    "pattern": i.pattern,
                }
                for i in result.issues
            ]
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    elif args.ci:
        # GitHub Actions 형식
        for issue in result.issues:
            level = "error" if issue.severity == "CRITICAL" else "warning"
            print(f"::{level} file={issue.file},line={issue.line}::{issue.message}")
    else:
        print(format_report(result))

    # 종료 코드
    if not result.passed:
        sys.exit(1)
    elif args.strict and result.warning_count > 0:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
