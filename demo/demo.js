"use strict";

var SCENARIOS = {
  dropoff_normal: {
    label: "등원 정상 흐름",
    steps: [
      {
        state: "BOARDING",
        level: "INFO",
        text: "등원 준비 중입니다. 뒷좌석 승차와 안전벨트를 확인해 주세요.",
        door: "OPEN",
        belt: false,
        ignition: "OFF",
        lock: "UNLOCKED",
        hvac: false,
        temp: null
      },
      {
        state: "ONBOARD",
        level: "INFO",
        text: "뒷좌석 승차가 확인되었습니다. 출발 전 안전벨트를 확인해 주세요.",
        door: "CLOSED",
        belt: true,
        ignition: "OFF",
        lock: "UNLOCKED",
        hvac: false,
        temp: null
      },
      {
        state: "DRIVING",
        level: "INFO",
        text: "안전 운전 중입니다. 운전 중에는 화면을 조작하지 마세요.",
        door: "CLOSED",
        belt: true,
        ignition: "ON",
        lock: "UNLOCKED",
        hvac: false,
        temp: null
      },
      {
        state: "ARRIVED",
        level: "REMIND",
        text: "도착했습니다. 등원 하차 전 뒷좌석을 확인해 주세요.",
        door: "CLOSED",
        belt: true,
        ignition: "OFF",
        lock: "UNLOCKED",
        hvac: false,
        temp: null
      },
      {
        state: "ALIGHTING",
        level: "INFO",
        text: "하차 중입니다. 뒷좌석이 비었는지 확인해 주세요.",
        door: "OPEN",
        belt: false,
        ignition: "OFF",
        lock: "UNLOCKED",
        hvac: false,
        temp: null
      },
      {
        state: "COMPLETED",
        level: "INFO",
        text: "하차 확인이 완료되었습니다.",
        door: "CLOSED",
        belt: false,
        ignition: "OFF",
        lock: "UNLOCKED",
        hvac: false,
        temp: null
      }
    ]
  },
  forgotten_rising_temp: {
    label: "하차 깜빡 + 온도 상승",
    steps: [
      {
        state: "BOARDING",
        level: "INFO",
        text: "등원 준비 중입니다. 뒷좌석 승차와 안전벨트를 확인해 주세요.",
        door: "OPEN",
        belt: false,
        ignition: "OFF",
        lock: "UNLOCKED",
        hvac: false,
        temp: null
      },
      {
        state: "ONBOARD",
        level: "INFO",
        text: "뒷좌석 승차가 확인되었습니다. 출발 전 안전벨트를 확인해 주세요.",
        door: "CLOSED",
        belt: true,
        ignition: "OFF",
        lock: "UNLOCKED",
        hvac: false,
        temp: null
      },
      {
        state: "DRIVING",
        level: "INFO",
        text: "안전 운전 중입니다. 운전 중에는 화면을 조작하지 마세요.",
        door: "CLOSED",
        belt: true,
        ignition: "ON",
        lock: "UNLOCKED",
        hvac: false,
        temp: null
      },
      {
        state: "ARRIVED",
        level: "REMIND",
        text: "도착했습니다. 등원 하차 전 뒷좌석을 확인해 주세요.",
        door: "CLOSED",
        belt: true,
        ignition: "OFF",
        lock: "UNLOCKED",
        hvac: false,
        temp: null
      },
      {
        state: "EXCEPTION",
        level: "URGENT",
        text: "잠긴 차량의 뒷좌석에 동승자가 남아 있을 수 있습니다. 뒷좌석을 확인해 주세요.",
        door: "CLOSED",
        belt: true,
        ignition: "OFF",
        lock: "LOCKED",
        hvac: false,
        temp: null
      },
      {
        state: "EXCEPTION",
        level: "URGENT",
        text: "잠긴 차량의 뒷좌석에 동승자가 남아 있을 수 있습니다. 뒷좌석을 확인해 주세요.",
        door: "CLOSED",
        belt: true,
        ignition: "OFF",
        lock: "LOCKED",
        hvac: false,
        temp: 28
      },
      {
        state: "EXCEPTION",
        level: "URGENT",
        text: "잠긴 차량의 뒷좌석에 동승자가 남아 있을 수 있습니다. 실내 온도 32도입니다. 뒷좌석을 확인해 주세요.",
        door: "CLOSED",
        belt: true,
        ignition: "OFF",
        lock: "LOCKED",
        hvac: false,
        temp: 32
      },
      {
        state: "EXCEPTION",
        level: "URGENT",
        text: "위험합니다. 잠긴 차량의 뒷좌석에 동승자가 남아 있을 수 있고 실내 온도 35.5도입니다. 즉시 뒷좌석을 확인해 주세요.",
        door: "CLOSED",
        belt: true,
        ignition: "OFF",
        lock: "LOCKED",
        hvac: false,
        temp: 35.5
      }
    ]
  },
  pet_dropoff: {
    label: "반려동물 등원",
    steps: [
      {
        state: "BOARDING",
        level: "INFO",
        text: "등원 준비 중입니다. 뒷좌석 승차와 안전벨트를 확인해 주세요.",
        door: "OPEN",
        belt: false,
        ignition: "OFF",
        lock: "UNLOCKED",
        hvac: false,
        temp: null
      },
      {
        state: "ONBOARD",
        level: "INFO",
        text: "뒷좌석 승차가 확인되었습니다. 출발 전 안전벨트를 확인해 주세요.",
        door: "CLOSED",
        belt: true,
        ignition: "OFF",
        lock: "UNLOCKED",
        hvac: false,
        temp: null
      },
      {
        state: "DRIVING",
        level: "INFO",
        text: "안전 운전 중입니다. 운전 중에는 화면을 조작하지 마세요.",
        door: "CLOSED",
        belt: true,
        ignition: "ON",
        lock: "UNLOCKED",
        hvac: true,
        temp: null
      },
      {
        state: "ARRIVED",
        level: "REMIND",
        text: "도착했습니다. 등원 하차 전 뒷좌석을 확인해 주세요.",
        door: "CLOSED",
        belt: true,
        ignition: "OFF",
        lock: "UNLOCKED",
        hvac: false,
        temp: null
      },
      {
        state: "ALIGHTING",
        level: "INFO",
        text: "하차 중입니다. 뒷좌석이 비었는지 확인해 주세요.",
        door: "OPEN",
        belt: false,
        ignition: "OFF",
        lock: "UNLOCKED",
        hvac: false,
        temp: null
      },
      {
        state: "COMPLETED",
        level: "INFO",
        text: "하차 확인이 완료되었습니다.",
        door: "CLOSED",
        belt: false,
        ignition: "OFF",
        lock: "UNLOCKED",
        hvac: false,
        temp: null
      }
    ]
  }
};

var currentScenario = "dropoff_normal";
var currentStep = 0;

function levelClass(level) {
  return "level-" + String(level).toLowerCase();
}

function formatDoor(door) {
  return door === "OPEN" ? "열림" : "닫힘";
}

function formatBelt(belt) {
  return belt ? "체결" : "미체결";
}

function formatIgnition(ignition) {
  return ignition === "ON" ? "켜짐" : "꺼짐";
}

function formatLock(lock) {
  return lock === "LOCKED" ? "잠김" : "잠금 해제";
}

function formatHvac(hvac) {
  return hvac ? "켜짐" : "꺼짐";
}

function formatTemp(temp) {
  return temp === null || temp === undefined ? "-" : String(temp) + "℃";
}

function render() {
  var scenario = SCENARIOS[currentScenario];
  var steps = scenario.steps;
  var step = steps[currentStep];
  var isWarning = step.state === "EXCEPTION" || step.level === "URGENT";

  document.getElementById("vehicle-state").textContent = step.state;

  var guidanceLevel = document.getElementById("guidance-level");
  guidanceLevel.textContent = step.level;
  guidanceLevel.className = "level-badge " + levelClass(step.level);

  document.getElementById("guidance-text").textContent = step.text;
  document.getElementById("sig-door").textContent = formatDoor(step.door);
  document.getElementById("sig-belt").textContent = formatBelt(step.belt);
  document.getElementById("sig-ignition").textContent = formatIgnition(step.ignition);
  document.getElementById("sig-lock").textContent = formatLock(step.lock);
  document.getElementById("sig-hvac").textContent = formatHvac(step.hvac);
  document.getElementById("sig-temp").textContent = formatTemp(step.temp);

  var phoneCard = document.getElementById("phone-card");
  phoneCard.className = "phone-card " + levelClass(step.level) + (isWarning ? " is-warning" : "");

  var phoneLevel = document.getElementById("phone-level");
  phoneLevel.textContent = step.level;
  phoneLevel.className = "level-badge " + levelClass(step.level);

  document.getElementById("phone-state").textContent = step.state;
  document.getElementById("phone-text").textContent = step.text;
  document.getElementById("step-indicator").textContent = (currentStep + 1) + "/" + steps.length;
  document.getElementById("next-step").disabled = currentStep >= steps.length - 1;
}

function nextStep() {
  var steps = SCENARIOS[currentScenario].steps;
  if (currentStep < steps.length - 1) {
    currentStep += 1;
  }
  render();
}

function resetDemo() {
  currentStep = 0;
  render();
}

function changeScenario(event) {
  currentScenario = event.target.value;
  currentStep = 0;
  render();
}

document.getElementById("next-step").addEventListener("click", nextStep);
document.getElementById("reset").addEventListener("click", resetDemo);
document.getElementById("scenario-select").addEventListener("change", changeScenario);

function applyQueryParams() {
  if (typeof window === "undefined" || !window.location) {
    return;
  }
  var params = new URLSearchParams(window.location.search || "");
  var scenario = params.get("scenario");
  if (scenario && Object.prototype.hasOwnProperty.call(SCENARIOS, scenario)) {
    currentScenario = scenario;
  }
  var stepParam = params.get("step");
  if (stepParam !== null) {
    var stepNumber = parseInt(stepParam, 10);
    if (!isNaN(stepNumber)) {
      var maxIndex = SCENARIOS[currentScenario].steps.length - 1;
      currentStep = Math.min(Math.max(stepNumber - 1, 0), maxIndex);
    }
  }
  document.getElementById("scenario-select").value = currentScenario;
}

applyQueryParams();

render();
