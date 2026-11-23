"""Tests for function-level breakdown in /analyze and /optimize responses."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.function_extractor import (
    extract_analysis_functions,
    extract_optimization_functions,
)
from app.services.model_service import RawModelOutput
from app.services.optimization_service import OptimizationResult

STUDENT_CPP_CODE = """#include <iostream>
#include <iomanip>
#include <string>
#include <vector>

using namespace std;

struct Student {
    string name;
    vector<double> marks;
    double total;
    double average;
    double percentage;
    char grade;
};

double calculateTotal(const vector<double>& marks) {
    double sum = 0;
    for (double m : marks) sum += m;
    return sum;
}

double calculateAverage(double total, int count) {
    if (count == 0) return 0;
    return total / count;
}

double calculatePercentage(double total, double maxTotal) {
    if (maxTotal == 0) return 0;
    return (total / maxTotal) * 100.0;
}

char calculateGrade(double percentage) {
    if (percentage >= 90) return 'A';
    if (percentage >= 80) return 'B';
    if (percentage >= 70) return 'C';
    if (percentage >= 60) return 'D';
    if (percentage >= 50) return 'E';
    return 'F';
}

void inputMarks(Student& s, int subjectCount) {
    s.marks.resize(subjectCount);
    for (int i = 0; i < subjectCount; i++) {
        cout << "Enter mark " << i + 1 << ": ";
        cin >> s.marks[i];
    }
}

void computeResults(Student& s, double maxPerSubject) {
    int count = s.marks.size();
    s.total = calculateTotal(s.marks);
    s.average = calculateAverage(s.total, count);
    s.percentage = calculatePercentage(s.total, maxPerSubject * count);
    s.grade = calculateGrade(s.percentage);
}

void printReport(const Student& s) {
    cout << fixed << setprecision(2);
    cout << "\\n----- Report -----\\n";
    cout << "Name       : " << s.name << "\\n";
    cout << "Total      : " << s.total << "\\n";
    cout << "Average    : " << s.average << "\\n";
    cout << "Percentage : " << s.percentage << "%\\n";
    cout << "Grade      : " << s.grade << "\\n";
}

void printClassSummary(const vector<Student>& students) {
    if (students.empty()) return;
    double classTotal = 0;
    for (const auto& s : students) classTotal += s.total;
    double classAvg = classTotal / students.size();

    cout << "\\n----- Class Summary -----\\n";
    cout << "Students    : " << students.size() << "\\n";
    cout << "Class Total : " << classTotal << "\\n";
    cout << "Class Avg   : " << classAvg << "\\n";

    const Student* top = &students[0];
    for (const auto& s : students)
        if (s.percentage > top->percentage) top = &s;
    cout << "Top Student : " << top->name << " (" << top->percentage << "%)\\n";
}

int main() {
    int studentCount, subjectCount;
    double maxPerSubject;
    return 0;
}
"""


@pytest.fixture
def client():
    return TestClient(app)


def test_extract_analysis_functions_student_example():
    """Verify that extract_analysis_functions finds all 9 functions in order."""
    commented = "// Commented version\n" + STUDENT_CPP_CODE
    items = extract_analysis_functions(
        code=STUDENT_CPP_CODE,
        commented_code=commented,
        analysis=None,
        docs=[],
        global_explanation="Computes student marks and prints grade summary report.",
    )

    assert len(items) == 9
    names = [item.name for item in items]
    assert names == [
        "calculateTotal",
        "calculateAverage",
        "calculatePercentage",
        "calculateGrade",
        "inputMarks",
        "computeResults",
        "printReport",
        "printClassSummary",
        "main",
    ]

    calc_total = items[0]
    assert calc_total.name == "calculateTotal"
    assert "double calculateTotal" in calc_total.code
    assert calc_total.start_line > 0
    assert calc_total.end_line >= calc_total.start_line
    assert calc_total.explanation != ""


def test_analyze_endpoint_returns_functions(client):
    """POST /analyze must include 'functions' array in its JSON response."""
    mock_model_output = RawModelOutput(
        commented_code="// Model commented\n" + STUDENT_CPP_CODE,
        explanation="Analyzed student management code.",
        line_comments=[],
        anchor_stats={"exact": 0, "relocated": 0, "dropped": 0, "kept": 0},
        verified=True,
    )

    with patch("app.services.model_service.run_model", return_value=mock_model_output):
        response = client.post(
            "/analyze",
            json={"code": STUDENT_CPP_CODE, "language": "cpp"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "functions" in data
        assert isinstance(data["functions"], list)
        assert len(data["functions"]) == 9

        first_fn = data["functions"][0]
        assert first_fn["name"] == "calculateTotal"
        assert "code" in first_fn
        assert "commented_code" in first_fn
        assert "explanation" in first_fn
        assert "start_line" in first_fn
        assert "end_line" in first_fn


def test_optimize_endpoint_returns_functions(client):
    """POST /optimize must return 'functions' array with per-function speedup and status."""
    multi_fn_code = """int helper() {
    return 42;
}

int fib(int n) {
    if (n <= 1) return n;
    return fib(n - 1) + fib(n - 2);
}
"""

    optimized_fib_code = """int helper() {
    return 42;
}

int fib(int n) {
    if (n <= 1) return n;
    int a = 0, b = 1;
    for (int i = 2; i <= n; i++) {
        int c = a + b;
        a = b;
        b = c;
    }
    return b;
}
"""

    mock_result = OptimizationResult(
        code=optimized_fib_code,
        changed=True,
        verified=True,
        speedup=3.4,
        note="Converted recursion to iterative loop.",
        target_fn_name="fib",
        isolated_proposal="""int fib(int n) {
    if (n <= 1) return n;
    int a = 0, b = 1;
    for (int i = 2; i <= n; i++) {
        int c = a + b;
        a = b;
        b = c;
    }
    return b;
}""",
    )

    with patch("app.services.optimization_service.optimize_checked", return_value=mock_result):
        response = client.post(
            "/optimize",
            json={"code": multi_fn_code, "source": "web", "mode": "loop"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "functions" in data
        assert len(data["functions"]) == 2

        fn_map = {f["name"]: f for f in data["functions"]}
        assert "helper" in fn_map
        assert "fib" in fn_map

        # helper was not changed
        assert fn_map["helper"]["changed"] is False
        assert fn_map["helper"]["speedup"] == 1.0

        # fib was optimized
        assert fn_map["fib"]["changed"] is True
        assert fn_map["fib"]["verified"] is True
        assert fn_map["fib"]["speedup"] == 3.4
        assert len(fn_map["fib"]["diff"]) > 0


def test_extract_optimization_functions_no_changes():
    """Verify unchanged optimization returns all functions with changed=False."""
    code = "int square(int x) { return x * x; }"
    result = OptimizationResult(
        code=code,
        changed=False,
        verified=True,
        speedup=1.0,
        note="Already optimal.",
    )
    items = extract_optimization_functions(code, code, result)
    assert len(items) == 1
    assert items[0].name == "square"
    assert items[0].changed is False
    assert items[0].speedup == 1.0
    assert items[0].verified is True
    assert items[0].diff == []
