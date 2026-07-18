import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

# ================== CONFIGURATION ==================
# Update this path to your advanced model directory
# e.g., "/Volumes/Data/newtraining/advanced_codet5_v2"
MODEL_PATH = "/Volumes/Data/saffi/fyp_backend/trained_model/fyp_models/archive/model_checkpoints/checkpoint-9604"
DEVICE = "cuda" if torch.cuda.is_available()  else "cpu"
# ===================================================
print(DEVICE)




import time

def generate_advanced_output(code, model, tokenizer):
    """
    Simulates the 'comment and explain' task trained in the advanced pipeline.
    """
    # The prefix MUST match what was used in train_full_pipeline.py
    input_text = f"comment and explain: {code}"
    
    inputs = tokenizer(
        input_text, 
        return_tensors="pt", 
        truncation=True, 
        max_length=512
    ).to(DEVICE)
    
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=384,
            num_beams=4,
            do_sample=True,
            top_p=0.95,
            temperature=0.4,
            repetition_penalty=1.05,  # Lowered so it doesn't penalize '//' characters
            early_stopping=True
        )
    
    return tokenizer.decode(outputs[0], skip_special_tokens=True)

def main():
    print(f"Loading advanced model from {MODEL_PATH}...")
    try:
        tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
        model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_PATH).to(DEVICE)
        model.eval()
        print("✅ Model loaded successfully.\n")
    except Exception as e:
        print(f"❌ Error loading model: {e}")
        return

    test_cases = {
        "DIAGNOSTIC (Training Style)": """
int calculate_sum(int n) {
    int sum = 0;
    for (int i = 1; i <= n; i++) {
        sum += i;
    }
    return sum;
}
        """,
        "HARD - Recursion & Logic": """
int fibonacci(int n) {
    if (n <= 1) return n;
    return fibonacci(n - 1) + fibonacci(n - 2);
}
        """,
        "REAL-WORLD - Pointer Logic": """
void deleteNode(Node* &head, int val) {
    if (head == nullptr) return;
    if (head->data == val) {
        Node* temp = head;
        head = head->next;
        delete temp;
        return;
    }
}
        """,
        "COMPLEX - Dynamic Programming (Coin Change)": """
int coinChange(vector<int>& coins, int amount) {
    vector<int> dp(amount + 1, amount + 1);
    dp[0] = 0;
    for (int i = 1; i <= amount; i++) {
        for (int coin : coins) {
            if (i - coin >= 0) {
                dp[i] = min(dp[i], dp[i - coin] + 1);
            }
        }
    }
    return dp[amount] > amount ? -1 : dp[amount];
}
        """,
        "COMPLEX - Graph DFS (Connected Components)": """
void dfs(int v, vector<vector<int>>& adj, vector<bool>& visited) {
    visited[v] = true;
    for (int u : adj[v]) {
        if (!visited[u]) {
            dfs(u, adj, visited);
        }
    }
}
        """,
        "STRING - Anagram Check": """
bool isAnagram(string s, string t) {
    if (s.length() != t.length()) return false;
    vector<int> counts(26, 0);
    for (int i = 0; i < s.length(); i++) {
        counts[s[i] - 'a']++;
        counts[t[i] - 'a']--;
    }
    for (int count : counts) {
        if (count != 0) return false;
    }
    return true;
}
        """,
        "EASY - Find Maximum": """
int findMax(vector<int>& nums) {
    int maxVal = nums[0];
    for (int i = 1; i < nums.size(); i++) {
        if (nums[i] > maxVal) maxVal = nums[i];
    }
    return maxVal;
}
    """,
    "EASY - Reverse String": """
void reverseString(vector<char>& s) {
    int left = 0, right = s.size() - 1;
    while (left < right) {
        swap(s[left++], s[right--]);
    }
}
    """,

    # --- MEDIUM: Trees, Sorting & Two-Pointers ---
    "MEDIUM - Binary Tree Inorder": """
void inorder(TreeNode* root, vector<int>& res) {
    if (!root) return;
    inorder(root->left, res);
    res.push_back(root->val);
    inorder(root->right, res);
}
    """,
    "MEDIUM - Merge Intervals": """
vector<vector<int>> merge(vector<vector<int>>& intervals) {
    if (intervals.empty()) return {};
    sort(intervals.begin(), intervals.end());
    vector<vector<int>> merged;
    for (auto interval : intervals) {
        if (merged.empty() || merged.back()[1] < interval[0]) {
            merged.push_back(interval);
        } else {
            merged.back()[1] = max(merged.back()[1], interval[1]);
        }
    }
    return merged;
}
    """,

    # --- HARD: Advanced Optimization & State ---
    "HARD - Sliding Window Maximum": """
vector<int> maxSlidingWindow(vector<int>& nums, int k) {
    deque<int> dq;
    vector<int> result;
    for (int i = 0; i < nums.size(); i++) {
        if (!dq.empty() && dq.front() == i - k) dq.pop_front();
        while (!dq.empty() && nums[dq.back()] < nums[i]) dq.pop_back();
        dq.push_back(i);
        if (i >= k - 1) result.push_back(nums[dq.front()]);
    }
    return result;
}
    """,
    "HARD - Dijkstra's Shortest Path": """
vector<int> dijkstra(int n, vector<vector<pair<int, int>>>& adj, int src) {
    priority_queue<pair<int, int>, vector<pair<int, int>>, greater<pair<int, int>>> pq;
    vector<int> dist(n, INT_MAX);
    dist[src] = 0;
    pq.push({0, src});
    while (!pq.empty()) {
        int d = pq.top().first, u = pq.top().second;
        pq.pop();
        if (d > dist[u]) continue;
        for (auto& edge : adj[u]) {
            if (dist[u] + edge.second < dist[edge.first]) {
                dist[edge.first] = dist[u] + edge.second;
                pq.push({dist[edge.first], edge.first});
            }
        }
    }
    return dist;
}
    """,

    # --- EDGE CASE: Bitwise & Math ---
    "EDGE CASE - Single Number": """
int singleNumber(vector<int>& nums) {
    int res = 0;
    for (int n : nums) res ^= n;
    return res;
}
    """,

    # --- MEDIUM: Linked Lists, Binary Search & Tries ---
    "MEDIUM - Linked List Cycle": """
bool hasCycle(ListNode *head) {
    if (!head || !head->next) return false;
    ListNode *slow = head;
    ListNode *fast = head->next;
    while (slow != fast) {
        if (!fast || !fast->next) return false;
        slow = slow->next;
        fast = fast->next->next;
    }
    return true;
}
    """,
    "MEDIUM - Binary Search (Safe)": """
int search(vector<int>& nums, int target) {
    int low = 0, high = nums.size() - 1;
    while (low <= high) {
        int mid = low + (high - low) / 2;
        if (nums[mid] == target) return mid;
        if (nums[mid] < target) low = mid + 1;
        else high = mid - 1;
    }
    return -1;
}
    """,
    "MEDIUM - Trie Insertion": """
void insert(string word) {
    TrieNode* curr = root;
    for (char c : word) {
        if (!curr->children[c - 'a']) {
            curr->children[c - 'a'] = new TrieNode();
        }
        curr = curr->children[c - 'a'];
    }
    curr->isEndOfWord = true;
}
    """,

    # --- DIFFICULT: State Management & Optimization ---
    "DIFFICULT - Trapping Rain Water": """
int trap(vector<int>& height) {
    int left = 0, right = height.size() - 1;
    int leftMax = 0, rightMax = 0, ans = 0;
    while (left < right) {
        if (height[left] < height[right]) {
            height[left] >= leftMax ? leftMax = height[left] : ans += (leftMax - height[left]);
            left++;
        } else {
            height[right] >= rightMax ? rightMax = height[right] : ans += (rightMax - height[right]);
            right--;
        }
    }
    return ans;
}
    """,
    "DIFFICULT - LRU Cache": """
class LRUCache {
    int capacity;
    list<pair<int, int>> cache;
    unordered_map<int, list<pair<int, int>>::iterator> m;
public:
    LRUCache(int cap) : capacity(cap) {}
    int get(int key) {
        if (m.find(key) == m.end()) return -1;
        cache.splice(cache.begin(), cache, m[key]);
        return m[key]->second;
    }
};
    """,
    "DIFFICULT - Randomized QuickSort": """
void quickSort(vector<int>& arr, int low, int high) {
    if (low < high) {
        int pivotIndex = low + rand() % (high - low + 1);
        swap(arr[pivotIndex], arr[high]);
        int pivot = arr[high], i = low - 1;
        for (int j = low; j < high; j++) {
            if (arr[j] < pivot) swap(arr[++i], arr[j]);
        }
        swap(arr[i + 1], arr[high]);
        quickSort(arr, low, i);
        quickSort(arr, i + 2, high);
    }
}
    """,

    # --- HARD: Backtracking & String Algorithms ---
    "HARD - Longest Palindromic Substring (DP)": """
string longestPalindrome(string s) {
    int n = s.size();
    if (n == 0) return "";
    vector<vector<bool>> dp(n, vector<bool>(n, false));
    int start = 0, maxLen = 1;
    for (int i = 0; i < n; i++) dp[i][i] = true;
    for (int len = 2; len <= n; len++) {
        for (int i = 0; i <= n - len; i++) {
            int j = i + len - 1;
            if (s[i] == s[j] && (len == 2 || dp[i+1][j-1])) {
                dp[i][j] = true;
                if (len > maxLen) { start = i; maxLen = len; }
            }
        }
    }
    return s.substr(start, maxLen);
}
    """,
    "HARD - N-Queens": """
void solve(int row, int n, vector<int>& cols, vector<string>& board, vector<vector<string>>& res) {
    if (row == n) { res.push_back(board); return; }
    for (int col = 0; col < n; col++) {
        bool safe = true;
        for (int r = 0; r < row; r++) {
            if (cols[r] == col || abs(row - r) == abs(col - cols[r])) {
                safe = false; break;
            }
        }
        if (safe) {
            cols[row] = col; board[row][col] = 'Q';
            solve(row + 1, n, cols, board, res);
            board[row][col] = '.';
        }
    }
}
    """,
    "HARD - KMP String Matching": """
vector<int> computeLPS(string pattern) {
    int m = pattern.size(), len = 0, i = 1;
    vector<int> lps(m, 0);
    while (i < m) {
        if (pattern[i] == pattern[len]) lps[i++] = ++len;
        else if (len != 0) len = lps[len - 1];
        else lps[i++] = 0;
    }
    return lps;
}
    """
    }

    print("="*60)
    print("🚀 CODET5 ADVANCED TEST SUITE (Code + Verification + Explanation)")
    print("="*60)

    for name, code in test_cases.items():
        print(f"\n>>> TESTING: {name}")
        print("-" * 20)
        print("INPUT RAW CODE:")
        print(code.strip())
        
        print("\nMODEL GENERATED OUTPUT:")
        t0 = time.time()
        result = generate_advanced_output(code.strip(), model, tokenizer)
        print(result)
        print(f"[took {time.time() - t0:.1f}s]")
        print("-" * 60)

if __name__ == "__main__":
    main()
