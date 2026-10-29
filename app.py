"""
Flask Web Application for Distributed Mutual Exclusion Simulator Using Lamport's Algorithm.
Provides RESTful APIs and serves the interactive visualization dashboard.
"""

import os
from flask import Flask, render_template, jsonify, request
from simulator.coordinator import SimulationCoordinator, ALGORITHM_NAMES

app = Flask(__name__)

# Global Simulation Coordinator instance (Default 4 processes, CS duration = 3 ticks)
coordinator = SimulationCoordinator(process_count=4, cs_duration=3)


@app.route("/")
def index():
    """Renders the main simulation dashboard."""
    state = coordinator.get_state()
    return render_template("index.html", stages=state["algorithm_stages"],
                           algorithm=state["algorithm"], algorithm_name=state["algorithm_name"])


@app.route("/api/state", methods=["GET"])
def get_state():
    """
    Returns full snapshot of simulator state:
    Processes, clocks, queues, messages, timeline, statistics, and invariant status.
    """
    event_filter = request.args.get("filter", "ALL")
    try:
        limit = int(request.args.get("limit", 40))
    except ValueError:
        limit = 40
    state = coordinator.get_state(event_filter=event_filter, event_limit=limit)
    return jsonify({"success": True, "data": state})


@app.route("/api/request", methods=["POST"])
def request_resource():
    """Triggers a resource request from a specified process."""
    data = request.get_json(silent=True) or {}
    pid = data.get("pid")
    if pid is None:
        return jsonify({"success": False, "error": "Missing process ID ('pid')."}), 400

    try:
        pid = int(pid)
    except ValueError:
        return jsonify({"success": False, "error": "Process ID must be an integer."}), 400

    success, message = coordinator.request_resource(pid)
    state = coordinator.get_state()
    return jsonify({
        "success": success,
        "message": message,
        "data": state
    }), (200 if success else 400)


@app.route("/api/concurrent", methods=["POST"])
def concurrent_requests():
    """Triggers concurrent requests from multiple processes."""
    data = request.get_json(silent=True) or {}
    pids = data.get("pids")
    if pids and isinstance(pids, list):
        try:
            pids = [int(p) for p in pids]
        except ValueError:
            pids = None

    success, message = coordinator.trigger_concurrent_requests(pids)
    state = coordinator.get_state()
    return jsonify({
        "success": success,
        "message": message,
        "data": state
    }), (200 if success else 400)


@app.route("/api/step", methods=["POST"])
def step():
    """Advances the simulation by one discrete event (one message delivery or one CS tick)."""
    step_result = coordinator.step()
    state = coordinator.get_state()
    return jsonify({
        "success": True,
        "step_result": step_result,
        "data": state
    })


@app.route("/api/start", methods=["POST"])
def start_simulation():
    """Starts automatic background simulation."""
    coordinator.start_auto()
    return jsonify({
        "success": True,
        "message": "Automatic simulation started.",
        "is_running": coordinator.is_running
    })


@app.route("/api/pause", methods=["POST"])
def pause_simulation():
    """Pauses automatic background simulation."""
    coordinator.pause_auto()
    return jsonify({
        "success": True,
        "message": "Simulation paused.",
        "is_running": coordinator.is_running
    })


@app.route("/api/reset", methods=["POST"])
def reset_simulation():
    """Resets the simulation to the initial state."""
    coordinator.reset()
    state = coordinator.get_state()
    return jsonify({
        "success": True,
        "message": "Simulation reset successfully.",
        "data": state
    })


@app.route("/api/config", methods=["POST"])
def configure_simulation():
    """
    Configures simulation parameters:
      - process_count: Number of processes (3-8)
      - speed_ms: Delay in milliseconds (50-3000ms)
      - cs_duration: Critical section ticks (1-15)
    """
    data = request.get_json(silent=True) or {}

    if "algorithm" in data:
        if not isinstance(data["algorithm"], str) or data["algorithm"] not in ALGORITHM_NAMES:
            return jsonify({"success": False, "error": "Choose Lamport or Ricart–Agrawala."}), 400
        coordinator.set_algorithm(data["algorithm"])

    if "process_count" in data:
        try:
            p_count = int(data["process_count"])
            coordinator.set_process_count(p_count)
        except ValueError:
            pass

    if "speed_ms" in data:
        try:
            speed = int(data["speed_ms"])
            coordinator.set_speed(speed)
        except ValueError:
            pass

    if "cs_duration" in data:
        try:
            duration = int(data["cs_duration"])
            coordinator.set_cs_duration(duration)
        except ValueError:
            pass

    state = coordinator.get_state()
    return jsonify({
        "success": True,
        "message": "Configuration updated.",
        "data": state
    })


@app.route("/api/algorithm", methods=["GET"])
def get_algorithm():
    """Returns educational descriptions of algorithm stages."""
    state = coordinator.get_state()
    return jsonify({
        "success": True,
        "algorithm": state["algorithm"],
        "stages": state["algorithm_stages"]
    })


if __name__ == "__main__":
    # Local development server on port 5000
    print("=" * 70)
    print(" Lamport's Distributed Mutual Exclusion Simulator")
    print(" Access at: http://localhost:5000")
    print("=" * 70)
    app.run(host="0.0.0.0", port=5000, debug=True)
