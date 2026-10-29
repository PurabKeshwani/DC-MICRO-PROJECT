# Distributed Mutual Exclusion Simulator: Lamport and Ricart–Agrawala

**Course:** Distributed Computing (BTech Computer Science & Engineering / Information Technology)  
**Academic Level:** College Practical Demonstration, Lab Project & Viva Voce Reference  
**Technology Stack:** Python 3, Flask, HTML5, CSS3, JavaScript, SVG Topology Visualizer  

---

## Choose an algorithm

Use the **Algorithm** dropdown to select **Lamport** or **Ricart–Agrawala**. Changing it clears the current run and pauses playback; process count, step delay, and CS duration stay the same.

- **Lamport:** local request queues, REQUEST / REPLY / RELEASE, and 3(N−1) messages per completed request.
- **Ricart–Agrawala:** REQUEST / REPLY only and 2(N−1) messages. Reply immediately when idle or when the incoming request has priority. Otherwise hold the reply until exit. Enter after every peer replies.

The same diagram, step controls, live comments, inspector, and history work for both protocols. In Ricart–Agrawala, process cards show **Deferred replies**: peers this process owes a reply after it exits. This is local bookkeeping, not a new message type. The observer lists active requests for teaching and does not grant access.

Reference: [Ricart and Agrawala, original 1981 paper](https://courses.grainger.illinois.edu/cs425/fa2023/358527.ricart-agrawala.pdf). The existing FIFO network is reused for both demonstrations; both assume reliable delivery and failure-free processes.

---

## 1. Abstract

Distributed Mutual Exclusion is a fundamental problem in distributed systems where concurrent autonomous nodes without shared memory or a global physical clock must coordinate access to a single shared, non-shareable critical resource. 

This project presents a complete, fully functional, web-based interactive simulator that implements **Leslie Lamport's 1978 Distributed Mutual Exclusion Algorithm** using logical clocks and deterministic total ordering. The system explicitly simulates distributed message passing (`REQUEST`, `REPLY`, `RELEASE`), maintains private request queues per process, verifies the strict mutual exclusion safety invariant ($\text{Processes in CS} \le 1$), and features an educational step-by-step visualizer with a live event log, SVG topology animator, and automated test suite.

---

## 2. Problem Statement

In single-system computing, mutual exclusion is easily achieved using hardware-supported atomic primitives (e.g., Test-and-Set, semaphores, or OS kernel mutex locks) because all threads share the same physical memory and clock.

In a **distributed system**, however:
1. There is **no shared physical memory** or centralized storage to maintain a lock variable.
2. There is **no global physical clock** to synchronize events or determine exact real-time ordering.
3. Network delay is unpredictable and message delivery is asynchronous.

The problem is to devise an algorithm where $N$ independent processes coordinate access to a shared resource such that:
- **Safety:** At most one process executes inside the Critical Section at any time.
- **Liveness:** Deadlock-free and starvation-free execution.
- **Fairness:** Requests are granted strictly in the order of their logical timestamps (First-Come, First-Served based on causality).

---

## 3. Distributed vs. Centralized Mutual Exclusion

| Metric / Dimension | Centralized Coordinator Approach | Lamport's Distributed Algorithm |
| :--- | :--- | :--- |
| **Architecture** | Single coordinator node grants permission | Fully distributed peer-to-peer coordination |
| **Single Point of Failure (SPOF)** | High: If coordinator crashes, entire system halts | Low: No central coordinator; processes act as peers |
| **Bottleneck** | Coordinator becomes a performance bottleneck | Workload and message processing distributed across all nodes |
| **Message Complexity** | 3 messages per CS entry (Request, Grant, Release) | $3(N - 1)$ messages per CS entry |
| **Synchronization Basis** | Coordinator's local queue | Distributed Lamport Logical Clocks + Total Ordering |
| **Fairness** | Subject to coordinator receipt order | Strictly ordered by logical causality $(T, P_i)$ |

> **Simulation Disclosure:** This project simulates distributed message passing among concurrent processes within a unified application runtime. Processes maintain independent memory, clocks, and local queues, exchanging message structures via a modular message passing network layer that can be plugged into real network sockets.

---

## 4. System Objectives

- **Algorithmic Authenticity:** Implement the authentic 5 rules of Lamport's Mutual Exclusion algorithm without shortcut global mutexes.
- **Independent State per Process:** Each process maintains its own private Lamport logical clock, local request queue, and reply tracker.
- **Interactive Controls:** Provide manual request triggering, concurrent clash generation, step-by-step event stepping, continuous auto-simulation, and dynamic process scaling (3 to 8 processes).
- **Dynamic Safety Invariant Verification:** Continuously evaluate the safety invariant $\sum [\text{State} == \text{IN\_CS}] \le 1$ at every single message delivery or execution tick.
- **Educational Transparency:** Display pedagogical explanations for every protocol event to prepare students for college viva examinations.

---

## 5. System Architecture

```
+-----------------------------------------------------------------------------------+
|                            INTERACTIVE WEB DASHBOARD                              |
|  - Process Cards (P1..Pn)   - SVG Topology Visualizer    - Message Timeline       |
|  - Shared Resource Panel    - Lamport Request Queue      - Live Protocol Log      |
+-----------------------------------------+-----------------------------------------+
                                          | HTTP / REST API (JSON)
                                          v
+-----------------------------------------------------------------------------------+
|                         FLASK APPLICATION CONTROLLER                              |
|  app.py: /api/state, /api/request, /api/concurrent, /api/step, /api/config        |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                             SIMULATION COORDINATOR                                |
|  - Concurrency Lock (threading.RLock)     - Step Engine (Discrete Event)          |
|  - Invariant Monitor (Violations: 0)       - Auto Background Thread                |
+---------------------+-------------------+-------------------+---------------------+
                      |                   |                   |
                      v                   v                   v
        +-----------------------+ +---------------+ +-----------------------+
        |  DistributedProcess   | |  MessageNet   | |  Lamport Algorithm    |
        |  - Local Clock (C_i)  | |  - In-Transit | |  - Tie-breaking rules |
        |  - Local Queue (Q_i)  | |  - History    | |  - Invariant checks   |
        |  - State & Replies    | |  - FIFO/Async | |  - Condition checks   |
        +-----------------------+ +---------------+ +-----------------------+
```

---

## 6. Lamport's Algorithm & Message Protocol

### 6.1 Logical Clock Update Rules
Each process $P_i$ maintains an integer counter $C_i$, initialized to 0:
1. **Internal Event / Sending Message:** Before sending a `REQUEST` or `RELEASE`, increment clock:
   $$C_i \leftarrow C_i + 1$$
2. **Receiving Message:** On receiving message $m$ with timestamp $T_m$:
   $$C_i \leftarrow \max(C_i, T_m) + 1$$

### 6.2 Deterministic Total Ordering
Requests are ordered by the relation $\prec$:
$$(T_i, P_i) \prec (T_j, P_j) \iff (T_i < T_j) \lor (T_i = T_j \land P_i < P_j)$$
Tie-breaking by Process ID ($P_i < P_j$) ensures deterministic, unambiguous ordering across all nodes.

### 6.3 Message Types
- `REQUEST(T, P_i)`: Broadcasted by $P_i$ when requesting the Critical Section.
- `REPLY(T, P_j)`: Sent by $P_j$ acknowledging $P_i$'s request.
- `RELEASE(T, P_i)`: Broadcasted by $P_i$ upon leaving the Critical Section.

### 6.4 Entry Conditions
Process $P_i$ is permitted to enter the Critical Section if and only if:
1. **Queue Head Condition:** The request $(T_i, P_i)$ is at the head of $P_i$'s local request queue $Q_i$.
2. **Reply Condition:** $P_i$ has received a message (specifically `REPLY`) timestamped later than $T_i$ from every other active process ($N - 1$ replies).

---

## 7. Algorithm Pseudocode

```text
// Initialization at Process Pi:
clock_i = 0
queue_i = []
replies_i = empty_set()
state_i = RELEASED

// Procedure: Request Resource (Pi)
procedure RequestResource():
    clock_i = clock_i + 1
    req = (timestamp = clock_i, process_id = Pi)
    queue_i.insert_sorted(req)
    state_i = REQUESTING
    replies_i.clear()
    for each peer Pj (j != i):
        send REQUEST(clock_i, Pi) to Pj

// Handler: On Receiving REQUEST(T_req, Pj) at Pi
handler OnReceiveRequest(T_req, Pj):
    clock_i = max(clock_i, T_req) + 1
    queue_i.insert_sorted((T_req, Pj))
    send REPLY(clock_i, Pi) to Pj

// Handler: On Receiving REPLY(T_rep, Pj) at Pi
handler OnReceiveReply(T_rep, Pj):
    clock_i = max(clock_i, T_rep) + 1
    replies_i.add(Pj)
    EvaluateCSEntry()

// Procedure: Evaluate Critical Section Entry
procedure EvaluateCSEntry():
    if queue_i.head() == (my_request) and size(replies_i) == (N - 1):
        state_i = IN_CRITICAL_SECTION
        EnterCriticalSection()

// Procedure: Release Resource (Pi)
procedure ReleaseResource():
    queue_i.remove((my_request))
    state_i = RELEASED
    replies_i.clear()
    clock_i = clock_i + 1
    for each peer Pj (j != i):
        send RELEASE(clock_i, Pi) to Pj

// Handler: On Receiving RELEASE(T_rel, Pj) at Pi
handler OnReceiveRelease(T_rel, Pj):
    clock_i = max(clock_i, T_rel) + 1
    queue_i.remove_by_process_id(Pj)
    EvaluateCSEntry()
```

---

## 8. Project Structure

```
distributed-mutual-exclusion/
│
├── app.py                      # Flask web server and REST API routes
├── requirements.txt            # Python dependencies (Flask, pytest)
├── README.md                   # Comprehensive project documentation & viva Q&A
│
├── simulator/                  # Core distributed computing engine
│   ├── __init__.py             # Module exports
│   ├── models.py               # Data models: Message, RequestEntry, ProcessState, Event
│   ├── ricart_agrawala.py       # Deferred replies and Ricart–Agrawala entry rules
│   ├── process.py              # DistributedProcess with Lamport clock & local queue
│   ├── message_network.py      # Simulated distributed async message passing network
│   ├── lamport_algorithm.py    # Formal invariant checks, tie-breaker logic & stages
│   └── coordinator.py          # Central coordinator, discrete-step engine, stats & auto mode
│
├── templates/
│   └── index.html              # Laptop teaching workspace with live commentary
│
├── static/
│   ├── css/
│   │   └── style.css           # Readable light theme with semantic message colours
│   └── js/
│       ├── visualizer.js       # SVG distributed network topology & in-transit packets
│       └── app.js              # Stable UI updates, local condition inspector & log filters
│
└── tests/
    ├── test_ricart_agrawala.py   # Priority, deferred replies, safety & message counts
    ├── __init__.py             # Test package initialization
    ├── test_lamport_algorithm.py # 10 unit test scenarios verifying algorithm rules
    └── test_api.py             # 17 integration tests for routes, teaching data & switching
```

---

## 9. Installation & Running Instructions

### 9.1 Prerequisites
- Python 3.9 or newer (tested on Python 3.10, 3.11, 3.12, 3.13, 3.14)
- A modern web browser (Google Chrome, Firefox, Microsoft Edge, Safari)

### 9.2 Step-by-Step Setup

1. **Open PowerShell or Command Prompt in the project folder:**
   ```powershell
   cd D:\DC_MINIP\DC_MINIP
   ```

2. **(Optional) Create and activate a virtual environment:**
   ```powershell
   py -3.13 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. **Install dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```

4. **Launch the simulator server:**
   ```powershell
   python app.py
   ```

5. **Open the web dashboard in your browser:**
   ```
   http://127.0.0.1:5000
   ```

---

## 10. Running Automated Unit Tests

The test suite thoroughly verifies all 16 Lamport scenarios, 9 Ricart–Agrawala scenarios, and 17 API scenarios (42 total tests):

```powershell
python -m unittest discover -s tests -v
```

### Verified Test Cases:
1. `test_01_single_process_request`: Single process requests and acquires CS.
2. `test_02_two_processes_different_times`: Sequential requests without contention.
3. `test_03_two_processes_simultaneous_requests`: Concurrent requests resolve safely.
4. `test_04_multiple_concurrent_requests`: 3 concurrent processes coordinate without conflict.
5. `test_05_equal_logical_timestamps_tie_breaking`: Deterministic resolution via Process ID.
6. `test_06_process_entering_and_leaving_cs`: Complete lifecycle state transitions.
7. `test_07_correct_handling_of_request_reply_release_messages`: Protocol message verification.
8. `test_08_logical_clock_updates_on_message_receipt`: Lamport clock formula $C = \max(C, T) + 1$.
9. `test_09_resetting_simulation`: Full memory and queue cleanup verification.
10. `test_10_repeated_runs_and_invariant_check`: Stress-testing safety invariant across randomized trials.
11. `test_11_out_of_order_message_delivery`: Non-FIFO, out-of-order, and shuffled message delivery preserves safety.
12. `test_12_duplicate_reply_cannot_bypass_peers`: Sender identity tracking prevents duplicate replies from bypassing peer replies.
13. `test_13_self_reply_rejected`: Verifies self-replies are rejected and do not count toward peer replies.
14. `test_14_dynamic_invariant_violation_detection`: Invariant monitor actively flags multiple processes in CS.
15. `test_15_sequential_rerequest_clock_monotonicity`: Logical clock monotonically increases across sequential CS entries.
16. `test_16_max_processes_scale_eight`: Full 8-process cluster coordination ($3 \times (8-1) = 21$ msgs/entry).
17. `test_01` to `test_09` in `test_api.py`: Full REST API suite, config updates, and HTTP status codes.
18. `test_10` to `test_14` in `test_api.py`: Live explanations independent of filters, exact clock calculations, RELEASE cleanup status, separate action details, CS progress notes, and paused reset behaviour.

---

## 11. Interactive Dashboard User Guide

- **Next step (`Next step` button):** Advances one discrete event at a time. Allows examiners to see:
  1. Process $P_i$ broadcasting `REQUEST`.
  2. Peer processes receiving `REQUEST`, advancing clock, enqueuing, and replying `REPLY`.
  3. $P_i$ collecting replies until condition $N-1$ is met.
  4. $P_i$ entering Critical Section.
  5. $P_i$ completing duration, broadcasting `RELEASE`.
  6. Waiting processes dequeuing and taking turn.
- **Concurrent requests (`Concurrent requests` button):** Triggers requests from multiple processes at the exact same step to demonstrate how timestamp tie-breaking orders access.
- **Process Scaling (3 to 8 processes):** Reconfigures cluster size on the fly to observe how message complexity scales ($3 \times (N-1)$).
- **Step delay & CS duration:** Choose the delay between auto steps (0.6 to 3 seconds) and the critical-section duration (1 to 10 simulation ticks). CS ticks model work duration and are independent of Lamport logical clock values.

---

The laptop interface puts the message diagram beside its current explanation. Use **Start auto / Pause auto** for playback, or **Next step** for one delivery or CS tick. Pause auto before stepping manually. **Reset** and process-count changes return the simulator to a paused, clean run.

Select a process in the diagram, on its card, or in **Local entry conditions** to inspect why it can enter or must wait. The inspector uses that process's own queue and peer replies. **Observer overview** combines the local queues for teaching; it grants no permission. A request marked **Release pending** remains in a peer's queue until the RELEASE arrives.

Log filters affect only the protocol log. Expand a log event for its explanation, or open **Message history & algorithm reference** for packet details and the complete rules. The interface uses plain JavaScript and SVG; it no longer needs Bootstrap or Chart.js. The optional web font has local system-font fallbacks.

---

## 12. Viva Voce Questions and Model Answers

### Q1: What is the main objective of Lamport's Distributed Mutual Exclusion Algorithm?
**Answer:** The objective is to ensure that in a distributed system with no shared memory and no centralized coordinator, multiple processes can safely and fairly coordinate exclusive access to a shared resource such that at most one process is inside the critical section at any time, ordered strictly by causal logical timestamps.

### Q2: What is the message complexity of Lamport's Algorithm per Critical Section entry?
**Answer:** The message complexity is **$3(N - 1)$** messages per critical section entry:
- $N - 1$ `REQUEST` messages broadcasted to all peers.
- $N - 1$ `REPLY` messages received from all peers.
- $N - 1$ `RELEASE` messages broadcasted to all peers.

### Q3: What are Lamport's two necessary and sufficient conditions for a process to enter the Critical Section?
**Answer:**
1. The process's own request $(T_i, P_i)$ is at the head (smallest element) of its local request queue.
2. The process has received a message timestamped greater than $T_i$ (specifically `REPLY`) from every other active participating process ($N - 1$ replies).

### Q4: Why does a process need a REPLY from every other process before entering CS?
**Answer:** If process $P_i$ entered CS without waiting for replies from all peers, there might be another process $P_j$ that had issued a request with an earlier timestamp that is still in transit on the network. Waiting for replies from all processes guarantees that $P_i$ has observed all prior requests that could precede it.

### Q5: How are simultaneous requests with identical Lamport timestamps resolved?
**Answer:** They are ordered using a deterministic tie-breaker based on Process ID:
$$(T_a, P_a) < (T_b, P_b) \iff (T_a < T_b) \lor (T_a = T_b \land P_a < P_b)$$
Since process IDs are unique and fixed, every process reaches the exact same ordering decision without communication overhead.

### Q6: What happens if one process crashes in Lamport's algorithm?
**Answer:** Lamport's basic algorithm assumes failure-free nodes and reliable communication. If a process crashes and fails to send a `REPLY` or `RELEASE`, all waiting processes will be blocked indefinitely (deadlock). In fault-tolerant distributed systems, heartbeat failure detectors, timeouts, or quorum consensus protocols (such as Ricart-Agrawala with fault recovery or Raft/Paxos) are employed.

### Q7: How does Lamport's algorithm differ from Ricart-Agrawala?
**Answer:** Ricart-Agrawala is an optimization of Lamport's algorithm that eliminates explicit `RELEASE` messages. In Ricart-Agrawala, a process only replies if it does not want the resource or if its own request has lower priority; deferred replies serve as releases. This reduces message complexity from $3(N - 1)$ to $2(N - 1)$.

### Q8: What is the Safety Invariant verified by this project?
**Answer:** The invariant is that the number of processes in state `IN_CRITICAL_SECTION` is $\le 1$ at all times. In this simulator, every state transition immediately executes `verify_mutual_exclusion()`. Any violation will increment the counter and alert the dashboard. During all normal executions, the counter remains strictly 0.

---

## 13. Limitations & Future Enhancements

### Limitations:
1. **Network Simulation:** Communication is simulated in memory using an asynchronous in-transit message queue rather than physical network sockets.
2. **Crash Resilience:** Assumes reliable delivery without crash-stop or Byzantine node failures.

### Future Enhancements:
1. **Socket-Based Implementation:** Swap the modular `MessageNetwork` with Python `socket` / `asyncio` or ZeroMQ over TCP/IP across multiple physical machines.
2. **Additional Algorithms:** Extend the existing selector with Maekawa's Voting Quorum.
3. **Fault Injection Panel:** Allow users to simulate network partitions, dropped messages, and process crashes to study failure recovery mechanisms.

---

## 14. Conclusion

This project successfully demonstrates the theory, mechanics, and elegance of Leslie Lamport's classical Distributed Mutual Exclusion Algorithm. By combining explicit message representations, independent process data structures, live SVG network topology visualization, and rigorous automated testing, it provides students, faculty, and viva examiners with an intuitive, mathematically verified platform for learning and demonstrating distributed systems principles.
