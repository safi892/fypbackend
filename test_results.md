

{
    "input_code": "void bubbleSort(int arr[], int n) {\n    for (int i = 0; i < n-1; i++) {\n        for (int j = 0; j < n-i-1; j++) {\n            if (arr[j] > arr[j+1]) {\n                int temp = arr[j];\n                arr[j] = arr[j+1];\n                arr[j+1] = temp;\n            }\n        }\n    }\n}",
    "commented_code": "void bubbleSort(int arr[], int n) {\n    for (int i = 0; i < n-1; i++) {  // Outer loop: each pass places the next largest element at its correct position\n        for (int j = 0; j < n-i-1; j++) {  // Inner loop: compare adjacent elements and swap if they are in wrong order\n            if (arr[j] > arr[j+1]) {  // Swap elements only when they are out of order\n                int temp = arr[j];  // Store the element temporarily to avoid overwriting it\n                arr[j] = arr[j+1];  // Move the larger element to the front\n                arr[j+1] = temp;  // Place the stored element at its correct position\n            }\n        }\n    }\n}  // No action needed for the last element of the current pass",
    "explanation": "Purpose: Sorts an integer array in ascending order using the bubble sort algorithm.  \nInput: `int arr[]` – the array to be sorted; `int n` – number of elements in the array.  \nOutput: The array is reordered in‑place; the function returns `void`.  \nAlgorithm: Repeatedly iterates over the array, comparing each pair of adjacent elements and swapping them if they are in the wrong order. The outer loop repeats `n‑1` times, the inner loop runs from the start to the last unsorted element each time. This bubble‑sort runs in O(n²) time and O(1) extra space.",
    "analysis": {
        "language": "cpp",
        "functions": [
            {
                "name": "bubbleSort",
                "start_line": 1,
                "end_line": 11,
                "length": 11,
                "params": 2,
                "recursive": false,
                "max_loop_depth": 2,
                "has_comment": false,
                "has_doc": false
            }
        ],
        "function_count": 1,
        "recursive": false,
        "max_nested_loops": 2,
        "long_functions": [],
        "missing_comments": 1,
        "missing_docs": 1,
        "duplicate_functions": [],
        "loops": 2,
        "conditionals": 1,
        "cyclomatic_complexity": 4,
        "parser": "tree-sitter"
    },
    "suggestions": [
        "Nested loops up to depth 2 found. Reduce nesting or extract inner loops into helper functions.",
        "1 function(s) lack inline comments. Add short comments explaining non-obvious logic.",
        "1 function(s) lack documentation blocks. Add a description, parameters and return value."
    ],
    "documentation": [
        {
            "function": "bubbleSort",
            "description": "Function 'bubbleSort' contains loops (depth 2).",
            "parameters": [
                "param1",
                "param2"
            ],
            "returns": "See function signature for the return type."
        }
    ],
    "change_analysis": null,
    "translation": null,
    "line_comments": [
        {
            "line": 2,
            "code": "for (int i = 0; i < n-1; i++) {",
            "comment": "Outer loop: each pass places the next largest element at its correct position"
        },
        {
            "line": 3,
            "code": "for (int j = 0; j < n-i-1; j++) {",
            "comment": "Inner loop: compare adjacent elements and swap if they are in wrong order"
        },
        {
            "line": 4,
            "code": "if (arr[j] > arr[j+1]) {",
            "comment": "Swap elements only when they are out of order"
        },
        {
            "line": 5,
            "code": "int temp = arr[j];",
            "comment": "Store the element temporarily to avoid overwriting it"
        },
        {
            "line": 6,
            "code": "arr[j] = arr[j+1];",
            "comment": "Move the larger element to the front"
        },
        {
            "line": 7,
            "code": "arr[j+1] = temp;",
            "comment": "Place the stored element at its correct position"
        },
        {
            "line": 11,
            "code": "}",
            "comment": "No action needed for the last element of the current pass"
        }
    ],
    "anchor_stats": {
        "proposed": 7,
        "kept": 7,
        "exact": 1,
        "relocated": 6,
        "dropped": 0,
        "chunks": 1
    },
    "verified_comments": true,
    "needs_review": false
}












—————————————————————————————————————












{
    "input_code": "#include <iostream>\n#include <vector>\n#include <queue>\n#include <limits>\n#include <algorithm>\n#include <functional>\nusing namespace std;\n\nclass Graph {\nprivate:\n    int V;\n    vector<vector<pair<int, int>>> adj;\n\npublic:\n    Graph(int vertices) : V(vertices), adj(vertices) {}\n\n    void addEdge(int u, int v, int weight) {\n        if (u < 0 || v < 0 || u >= V || v >= V || weight < 0)\n            return;\n\n        adj[u].push_back({v, weight});\n    }\n\n    vector<int> shortestPath(int source) {\n        vector<int> distance(V, numeric_limits<int>::max());\n        vector<int> parent(V, -1);\n\n        priority_queue<pair<int, int>, vector<pair<int, int>>, greater<pair<int, int>>> pq;\n\n        distance[source] = 0;\n        pq.push({0, source});\n\n        while (!pq.empty()) {\n            auto [currentDistance, u] = pq.top();\n            pq.pop();\n\n            if (currentDistance > distance[u])\n                continue;\n\n            for (const auto& edge : adj[u]) {\n                int v = edge.first;\n                int weight = edge.second;\n\n                if (distance[u] != numeric_limits<int>::max() &&\n                    distance[u] + weight < distance[v]) {\n                    distance[v] = distance[u] + weight;\n                    parent[v] = u;\n                    pq.push({distance[v], v});\n                }\n            }\n        }\n\n        return distance;\n    }\n\n    void printAllPaths(int source, int destination) {\n        vector<bool> visited(V, false);\n        vector<int> path;\n\n        function<void(int)> dfs = [&](int current) {\n            visited[current] = true;\n            path.push_back(current);\n\n            if (current == destination) {\n                for (size_t i = 0; i < path.size(); ++i) {\n                    cout << path[i];\n                    if (i + 1 < path.size())\n                        cout << \" -> \";\n                }\n                cout << endl;\n            } else {\n                for (const auto& edge : adj[current]) {\n                    int next = edge.first;\n\n                    if (!visited[next])\n                        dfs(next);\n                }\n            }\n\n            path.pop_back();\n            visited[current] = false;\n        };\n\n        dfs(source);\n    }\n};\n\nint longestIncreasingSubsequence(const vector<int>& nums) {\n    if (nums.empty())\n        return 0;\n\n    vector<int> dp(nums.size(), 1);\n\n    for (size_t i = 1; i < nums.size(); ++i) {\n        for (size_t j = 0; j < i; ++j) {\n            if (nums[j] < nums[i]) {\n                dp[i] = max(dp[i], dp[j] + 1);\n            }\n        }\n    }\n\n    return *max_element(dp.begin(), dp.end());\n}\n\nint main() {\n    Graph graph(6);\n\n    graph.addEdge(0, 1, 4);\n    graph.addEdge(0, 2, 2);\n    graph.addEdge(1, 2, 5);\n    graph.addEdge(1, 3, 10);\n    graph.addEdge(2, 4, 3);\n    graph.addEdge(4, 3, 4);\n    graph.addEdge(3, 5, 11);\n\n    vector<int> distances = graph.shortestPath(0);\n\n    for (int i = 0; i < distances.size(); ++i) {\n        cout << \"Distance to \" << i << \": \";\n\n        if (distances[i] == numeric_limits<int>::max())\n            cout << \"INF\";\n        else\n            cout << distances[i];\n\n        cout << endl;\n    }\n\n    graph.printAllPaths(0, 5);\n\n    vector<int> values = {10, 9, 2, 5, 3, 7, 101, 18};\n\n    cout << \"LIS length: \"\n         << longestIncreasingSubsequence(values)\n         << endl;\n\n    return 0;\n}",
    "commented_code": "#include <iostream>\n#include <vector>\n#include <queue>\n#include <limits>\n#include <algorithm>\n#include <functional>\nusing namespace std;\n\nclass Graph {\nprivate:\n    int V;\n    vector<vector<pair<int, int>>> adj;  // adjacency list where each entry holds a list of (neighbor, weight) pairs\n\npublic:\n    Graph(int vertices) : V(vertices), adj(vertices) {}\n\n    void addEdge(int u, int v, int weight) {\n        if (u < 0 || v < 0 || u >= V || v >= V || weight < 0)  // Reject edges that violate the graph's vertex and weight constraints\n            return;  // If any condition fails, the edge is ignored\n\n        adj[u].push_back({v, weight});  // Insert the edge into the adjacency list; the pair {v, weight} is copied\n    }\n\n    vector<int> shortestPath(int source) {\n        vector<int> distance(V, numeric_limits<int>::max());\n        vector<int> parent(V, -1);\n\n        priority_queue<pair<int, int>, vector<pair<int, int>>, greater<pair<int, int>>> pq;\n\n        distance[source] = 0;\n        pq.push({0, source});\n\n        while (!pq.empty()) {\n            auto [currentDistance, u] = pq.top();\n            pq.pop();\n\n            if (currentDistance > distance[u])\n                continue;\n\n            for (const auto& edge : adj[u]) {\n                int v = edge.first;\n                int weight = edge.second;\n\n                if (distance[u] != numeric_limits<int>::max() &&\n                    distance[u] + weight < distance[v]) {  // Relax only if the edge leads to a shorter path\n                    distance[v] = distance[u] + weight;  // Update the shortest distance and record the predecessor\n                    parent[v] = u;\n                    pq.push({distance[v], v});  // Insert the vertex into the priority queue for future relaxation\n                }\n            }\n        }\n\n        return distance;\n    }\n\n    void printAllPaths(int source, int destination) {\n        vector<bool> visited(V, false);  // mark all vertices as unvisited\n        vector<int> path;  // stores the current path being explored\n\n        function<void(int)> dfs = [&](int current) {  // depth‑first search helper\n            visited[current] = true;  // mark current vertex as visited\n            path.push_back(current);  // add vertex to the current path\n\n            if (current == destination) {\n                for (size_t i = 0; i < path.size(); ++i) {  // output the entire path when it reaches the destination\n                    cout << path[i];\n                    if (i + 1 < path.size())\n                        cout << \" -> \";\n                }\n                cout << endl;  // end the line after printing all vertices\n            } else {\n                for (const auto& edge : adj[current]) {  // explore all outgoing edges from the current vertex\n                    int next = edge.first;  // get the target vertex of the edge\n\n                    if (!visited[next])  // only recurse if the target has not been visited yet\n                        dfs(next);  // continue DFS from the neighbor\n                }\n            }\n\n            path.pop_back();  // backtrack: remove the last vertex from the path\n            visited[current] = false;  // mark current vertex as unvisited for future paths\n        };\n\n        dfs(source);  // start DFS from the source vertex\n    }\n};  // No explicit destructor needed; the class is trivially destructible\n\nint longestIncreasingSubsequence(const vector<int>& nums) {\n    if (nums.empty())  // If the input vector is empty, there cannot be any increasing subsequence\n        return 0;\n\n    vector<int> dp(nums.size(), 1);  // dp[i] will store the length of the longest increasing subsequence ending at index i\n\n    for (size_t i = 1; i < nums.size(); ++i) {  // Iterate over each element starting from the second one\n        for (size_t j = 0; j < i; ++j) {  // Compare with every previous element to find the longest subsequence that can be extended\n            if (nums[j] < nums[i]) {  // If the current element is greater than the previous element, extending the subsequence ending at j can lead to a longer subsequence ending at i\n                dp[i] = max(dp[i], dp[j] + 1);  // Update dp[i] with the maximum length found so far\n            }\n        }\n    }\n\n    return *max_element(dp.begin(), dp.end());  // Return the maximum value in dp, which represents the length of the longest increasing subsequence\n}\n\nint main() {\n    Graph graph(6);  // Create a graph with 6 vertices\n\n    graph.addEdge(0, 1, 4);  // Add edges to the graph; each edge is (source, target, weight)\n    graph.addEdge(0, 2, 2);  // 0 → 1: weight 4\n    graph.addEdge(1, 2, 5);  // 1 → 2: weight 5\n    graph.addEdge(1, 3, 10);  // 1 → 3: weight 10\n    graph.addEdge(2, 4, 3);  // 2 → 4: weight 3\n    graph.addEdge(4, 3, 4);  // 4 → 3: weight 4\n    graph.addEdge(3, 5, 11);  // 3 → 5: weight 11\n\n    vector<int> distances = graph.shortestPath(0);  // Compute shortest path distances from vertex 0 to all others\n\n    for (int i = 0; i < distances.size(); ++i) {  // Print each distance; INF indicates unreachable\n        cout << \"Distance to \" << i << \": \";\n\n        if (distances[i] == numeric_limits<int>::max())\n            cout << \"INF\";\n        else\n            cout << distances[i];\n\n        cout << endl;\n    }\n\n    graph.printAllPaths(0, 5);\n\n    vector<int> values = {10, 9, 2, 5, 3, 7, 101, 18};\n\n    cout << \"LIS length: \"\n         << longestIncreasingSubsequence(values)\n         << endl;\n\n    return 0;\n}",
    "explanation": "Purpose: Compute shortest paths and all paths in an undirected weighted graph, and find the length of the longest increasing subsequence.  \nInput: Graph constructor takes vertex count; addEdge adds an edge with optional weight; shortestPath runs Dijkstra’s algorithm from source; printAllPaths performs a depth‑first search to list all paths from source to destination. longestIncreasingSubsequence uses dynamic programming to build a DP table where dp[i] = longest increasing subsequence ending at i, returning the maximum value.",
    "analysis": {
        "language": "cpp",
        "functions": [
            {
                "name": "main",
                "start_line": 105,
                "end_line": 138,
                "length": 34,
                "params": 0,
                "recursive": false,
                "max_loop_depth": 1,
                "has_comment": false,
                "has_doc": false
            },
            {
                "name": "longestIncreasingSubsequence",
                "start_line": 88,
                "end_line": 103,
                "length": 16,
                "params": 1,
                "recursive": false,
                "max_loop_depth": 2,
                "has_comment": false,
                "has_doc": false
            },
            {
                "name": "printAllPaths",
                "start_line": 56,
                "end_line": 85,
                "length": 30,
                "params": 2,
                "recursive": false,
                "max_loop_depth": 1,
                "has_comment": false,
                "has_doc": false
            },
            {
                "name": "shortestPath",
                "start_line": 24,
                "end_line": 54,
                "length": 31,
                "params": 1,
                "recursive": false,
                "max_loop_depth": 2,
                "has_comment": false,
                "has_doc": false
            },
            {
                "name": "addEdge",
                "start_line": 17,
                "end_line": 22,
                "length": 6,
                "params": 3,
                "recursive": false,
                "max_loop_depth": 0,
                "has_comment": false,
                "has_doc": false
            },
            {
                "name": "Graph",
                "start_line": 15,
                "end_line": 15,
                "length": 1,
                "params": 1,
                "recursive": false,
                "max_loop_depth": 0,
                "has_comment": false,
                "has_doc": false
            }
        ],
        "function_count": 6,
        "recursive": false,
        "max_nested_loops": 2,
        "long_functions": [],
        "missing_comments": 6,
        "missing_docs": 6,
        "duplicate_functions": [],
        "loops": 7,
        "conditionals": 9,
        "cyclomatic_complexity": 28,
        "parser": "tree-sitter"
    },
    "suggestions": [
        "Nested loops up to depth 2 found. Reduce nesting or extract inner loops into helper functions.",
        "6 function(s) lack inline comments. Add short comments explaining non-obvious logic.",
        "6 function(s) lack documentation blocks. Add a description, parameters and return value.",
        "High cyclomatic complexity (28). Simplify branching and consider early returns."
    ],
    "documentation": [
        {
            "function": "main",
            "description": "Function 'main' contains loops (depth 1).",
            "parameters": [],
            "returns": "See function signature for the return type."
        },
        {
            "function": "longestIncreasingSubsequence",
            "description": "Function 'longestIncreasingSubsequence' contains loops (depth 2).",
            "parameters": [
                "param1"
            ],
            "returns": "See function signature for the return type."
        },
        {
            "function": "printAllPaths",
            "description": "Function 'printAllPaths' contains loops (depth 1).",
            "parameters": [
                "param1",
                "param2"
            ],
            "returns": "See function signature for the return type."
        },
        {
            "function": "shortestPath",
            "description": "Function 'shortestPath' contains loops (depth 2).",
            "parameters": [
                "param1"
            ],
            "returns": "See function signature for the return type."
        },
        {
            "function": "addEdge",
            "description": "Function 'addEdge' performs a computation.",
            "parameters": [
                "param1",
                "param2",
                "param3"
            ],
            "returns": "See function signature for the return type."
        },
        {
            "function": "Graph",
            "description": "Function 'Graph' performs a computation.",
            "parameters": [
                "param1"
            ],
            "returns": "See function signature for the return type."
        }
    ],
    "change_analysis": null,
    "translation": null,
    "line_comments": [
        {
            "line": 12,
            "code": "vector<vector<pair<int, int>>> adj;",
            "comment": "adjacency list where each entry holds a list of (neighbor, weight) pairs"
        },
        {
            "line": 18,
            "code": "if (u < 0 || v < 0 || u >= V || v >= V || weight < 0)",
            "comment": "Reject edges that violate the graph's vertex and weight constraints."
        },
        {
            "line": 19,
            "code": "return;",
            "comment": "If any condition fails, the edge is ignored."
        },
        {
            "line": 21,
            "code": "adj[u].push_back({v, weight});",
            "comment": "Insert the edge into the adjacency list; the pair {v, weight} is copied."
        },
        {
            "line": 45,
            "code": "distance[u] + weight < distance[v]) {",
            "comment": "Relax only if the edge leads to a shorter path."
        },
        {
            "line": 46,
            "code": "distance[v] = distance[u] + weight;",
            "comment": "Update the shortest distance and record the predecessor."
        },
        {
            "line": 48,
            "code": "pq.push({distance[v], v});",
            "comment": "Insert the vertex into the priority queue for future relaxation."
        },
        {
            "line": 57,
            "code": "vector<bool> visited(V, false);",
            "comment": "mark all vertices as unvisited"
        },
        {
            "line": 58,
            "code": "vector<int> path;",
            "comment": "stores the current path being explored"
        },
        {
            "line": 60,
            "code": "function<void(int)> dfs = [&](int current) {",
            "comment": "depth‑first search helper"
        },
        {
            "line": 61,
            "code": "visited[current] = true;",
            "comment": "mark current vertex as visited"
        },
        {
            "line": 62,
            "code": "path.push_back(current);",
            "comment": "add vertex to the current path"
        },
        {
            "line": 65,
            "code": "for (size_t i = 0; i < path.size(); ++i) {",
            "comment": "output the entire path when it reaches the destination"
        },
        {
            "line": 70,
            "code": "cout << endl;",
            "comment": "end the line after printing all vertices"
        },
        {
            "line": 72,
            "code": "for (const auto& edge : adj[current]) {",
            "comment": "explore all outgoing edges from the current vertex"
        },
        {
            "line": 73,
            "code": "int next = edge.first;",
            "comment": "get the target vertex of the edge"
        },
        {
            "line": 75,
            "code": "if (!visited[next])",
            "comment": "only recurse if the target has not been visited yet"
        },
        {
            "line": 76,
            "code": "dfs(next);",
            "comment": "continue DFS from the neighbor"
        },
        {
            "line": 80,
            "code": "path.pop_back();",
            "comment": "backtrack: remove the last vertex from the path"
        },
        {
            "line": 81,
            "code": "visited[current] = false;",
            "comment": "mark current vertex as unvisited for future paths"
        },
        {
            "line": 84,
            "code": "dfs(source);",
            "comment": "start DFS from the source vertex"
        },
        {
            "line": 86,
            "code": "};",
            "comment": "No explicit destructor needed; the class is trivially destructible."
        },
        {
            "line": 89,
            "code": "if (nums.empty())",
            "comment": "If the input vector is empty, there cannot be any increasing subsequence."
        },
        {
            "line": 92,
            "code": "vector<int> dp(nums.size(), 1);",
            "comment": "dp[i] will store the length of the longest increasing subsequence ending at index i."
        },
        {
            "line": 94,
            "code": "for (size_t i = 1; i < nums.size(); ++i) {",
            "comment": "Iterate over each element starting from the second one."
        },
        {
            "line": 95,
            "code": "for (size_t j = 0; j < i; ++j) {",
            "comment": "Compare with every previous element to find the longest subsequence that can be extended."
        },
        {
            "line": 96,
            "code": "if (nums[j] < nums[i]) {",
            "comment": "If the current element is greater than the previous element, extending the subsequence ending at j can lead to a longer subsequence ending at i."
        },
        {
            "line": 97,
            "code": "dp[i] = max(dp[i], dp[j] + 1);",
            "comment": "Update dp[i] with the maximum length found so far."
        },
        {
            "line": 102,
            "code": "return *max_element(dp.begin(), dp.end());",
            "comment": "Return the maximum value in dp, which represents the length of the longest increasing subsequence."
        },
        {
            "line": 106,
            "code": "Graph graph(6);",
            "comment": "Create a graph with 6 vertices"
        },
        {
            "line": 108,
            "code": "graph.addEdge(0, 1, 4);",
            "comment": "Add edges to the graph; each edge is (source, target, weight)"
        },
        {
            "line": 109,
            "code": "graph.addEdge(0, 2, 2);",
            "comment": "0 → 1: weight 4"
        },
        {
            "line": 110,
            "code": "graph.addEdge(1, 2, 5);",
            "comment": "1 → 2: weight 5"
        },
        {
            "line": 111,
            "code": "graph.addEdge(1, 3, 10);",
            "comment": "1 → 3: weight 10"
        },
        {
            "line": 112,
            "code": "graph.addEdge(2, 4, 3);",
            "comment": "2 → 4: weight 3"
        },
        {
            "line": 113,
            "code": "graph.addEdge(4, 3, 4);",
            "comment": "4 → 3: weight 4"
        },
        {
            "line": 114,
            "code": "graph.addEdge(3, 5, 11);",
            "comment": "3 → 5: weight 11"
        },
        {
            "line": 116,
            "code": "vector<int> distances = graph.shortestPath(0);",
            "comment": "Compute shortest path distances from vertex 0 to all others"
        },
        {
            "line": 118,
            "code": "for (int i = 0; i < distances.size(); ++i) {",
            "comment": "Print each distance; INF indicates unreachable"
        }
    ],
    "anchor_stats": {
        "proposed": 42,
        "kept": 39,
        "exact": 10,
        "relocated": 29,
        "dropped": 3,
        "chunks": 7
    },
    "verified_comments": true,
    "needs_review": false
}
