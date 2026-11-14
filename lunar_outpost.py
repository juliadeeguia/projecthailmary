#!/usr/bin/env python3
"""
LUNAR OUTPOST: ARTEMIS BASE CAMP
================================
A turn-based survival and resource-management game for students.

You command a 4-person crew on a 90-day surface mission. Every day you decide
what each astronaut does and which systems get power. Oxygen, water, food,
power, radiation shielding, equipment condition and crew morale are all
connected, so a choice that fixes one problem can quietly create another.

Run it:
    python lunar_outpost.py              # Python 3.8+, no extra packages
    python lunar_outpost.py --seed 42    # repeatable mission (same events)
    python lunar_outpost.py --no-color   # plain text output

The numbers are simplified, but they are based on real mission planning
figures (for example, 0.84 kg of O2 per person per day, about 1.37 mSv/day of
surface radiation measured by Chang'e-4, and NASA's 600 mSv career limit).
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import textwrap

# ---------------------------------------------------------------------------
# Mission constants
# ---------------------------------------------------------------------------
MISSION_DAYS = 90
LUNAR_CYCLE = 30                 # simplified synodic month (real: 29.5 days)
CAREER_DOSE_LIMIT = 600.0        # mSv, NASA career limit (2022 standard)

O2_PER_CREW = 0.84               # kg of oxygen per person per day
WATER_PER_CREW = 4.0             # kg of water per person per day (gross)
FOOD_PER_CREW = 1.8              # kg of food per person per day
GCR_SURFACE_DOSE = 1.37          # mSv/day on the surface (Chang'e-4 data)

SOLAR_ARRAY_KWH = 30.0           # per array per day, sunlight only
REACTOR_KWH = 40.0               # per reactor per day, day AND night
BATTERY_KWH = 100.0              # storage per battery bank
HAB_BASE_KWH = 20.0              # air circulation, CO2 scrubbing, comms
HAB_NIGHT_HEAT_KWH = 12.0        # extra heating during the lunar night
ELECTROLYZER_O2 = 5.0            # kg O2/day per electrolyzer
ELECTROLYZER_KWH = 20.0
WATER_PER_KG_O2 = 1.13           # water split to make 1 kg of O2
RECYCLER_KWH = 8.0
RECYCLER_EFF = 0.90              # fraction of used water recovered
GREENHOUSE_KWH = 12.0
GREENHOUSE_FOOD = 1.5            # kg food/day per module once mature
GREENHOUSE_WATER = 1.0
GREENHOUSE_GROW_DAYS = 10
ROVER_KWH_PER_EVA = 6.0
LAB_KWH = 6.0

INITIAL_CARGO_BUDGET = 1500      # kg of extra cargo at launch
RESUPPLY_BUDGET = 1000           # kg per resupply lander
RESUPPLY_DAYS = [30, 60]

SITES = {
    "1": {
        "name": "Shackleton Crater Rim (South Pole)",
        "short": "Shackleton Rim",
        "night_days": 6,
        "ice_yield": 20.0,
        "science_mult": 1.0,
        "start_water": 1000.0,
        "difficulty": "EASIER",
        "desc": "A sunlit ridge beside permanently shadowed craters full of "
                "water ice. Short nights, lots of ice, modest science value.",
    },
    "2": {
        "name": "Schrodinger Basin (Far Side)",
        "short": "Schrodinger Basin",
        "night_days": 13,
        "ice_yield": 10.0,
        "science_mult": 1.3,
        "start_water": 1200.0,
        "difficulty": "MEDIUM",
        "desc": "A young impact basin with exposed deep crust. Long nights, "
                "some ice, high science value.",
    },
    "3": {
        "name": "Mare Tranquillitatis (Equator)",
        "short": "Mare Tranquillitatis",
        "night_days": 15,
        "ice_yield": 3.0,
        "science_mult": 1.6,
        "start_water": 1500.0,
        "difficulty": "HARD",
        "desc": "Near the Apollo 11 site. Full 15-day nights and almost no "
                "ice, but rare lava-tube geology worth a lot of science.",
    },
}

# Task code -> (label, is_eva)
TASKS = {
    "R": ("Rest", False),
    "M": ("Maintenance", False),
    "G": ("Tend greenhouse", False),
    "L": ("Lab research", False),
    "S": ("Storm shelter", False),
    "I": ("EVA: Mine ice", True),
    "B": ("EVA: Build shielding", True),
    "X": ("EVA: Geology survey", True),
}

SYSTEM_LABELS = {
    "habitat": "Habitat hull",
    "solar": "Solar arrays",
    "battery": "Battery banks",
    "reactor": "Fission reactor",
    "electrolyzer": "O2 electrolyzer",
    "recycler": "Water recycler",
    "greenhouse": "Greenhouse",
    "rover": "Excavator rover",
}

TOGGLEABLE = ["recycler", "electrolyzer", "greenhouse", "lab"]
TOGGLE_LABELS = {
    "recycler": "Water recycler",
    "electrolyzer": "O2 electrolyzer",
    "greenhouse": "Greenhouse grow lights",
    "lab": "Science lab",
}

# key -> (name, mass_kg, max_qty or None, description)
CARGO = [
    ("food", "Food pallet", 100, None, "+100 kg food"),
    ("parts", "Spare parts crate", 100, None, "+5 spare parts"),
    ("oxygen", "Oxygen tanks", 150, None, "+80 kg O2 (tanks are heavy)"),
    ("water", "Water tank", 200, None, "+200 kg water"),
    ("solar", "Solar array", 150, None, "+30 kWh/day, sunlight only"),
    ("battery", "Battery bank", 150, None, "+100 kWh storage"),
    ("reactor", "Fission reactor", 600, None, "+40 kWh/day, day and night"),
    ("greenhouse", "Greenhouse module", 400, None, "+1.5 kg food/day after 10 days"),
    ("electrolyzer", "Electrolyzer", 200, None, "+5 kg O2/day (uses water + power)"),
    ("shelter", "Storm shelter kit", 300, 1, "Water-walled refuge, blocks ~95% of solar storms"),
]

LESSONS = {
    "night": ("The lunar night",
              "Most of the Moon gets about 14 Earth days of darkness at a time. "
              "Solar power drops to zero, so every kWh has to come from "
              "batteries or a power source that works in the dark. Polar "
              "ridges are attractive sites partly because they stay lit longer."),
    "load_shedding": ("Prioritise your loads",
                      "Your power system had to switch equipment off. Engineers "
                      "rank loads: life-critical first (air, heat), then water, "
                      "then food, then science, and plan so shedding is rare."),
    "blackout": ("Power is life support",
                 "When the habitat lost power, heaters, fans and CO2 scrubbers "
                 "stopped. Real outposts size energy storage for the longest "
                 "night plus a margin, or add fission power."),
    "oxygen": ("Oxygen has no substitute",
               "People last only minutes without oxygen. Outposts keep a reserve "
               "of many days and make more by splitting water (electrolysis), "
               "which links your air supply to your water and power supplies."),
    "water": ("Water is the master resource",
              "Water is drunk, split into oxygen, used to grow food and can even "
              "block radiation. Recycling 90%+ of it is essential, and polar ice "
              "can top it up."),
    "recycler": ("Closing the loop",
                 "Without recycling, a crew of four goes through 16 kg of water a "
                 "day. With 90% recovery that drops to 1.6 kg. The ISS recovers "
                 "about 98% of its water."),
    "food": ("Food buffers",
             "Food can't be produced quickly: crops take weeks. Keep a buffer and "
             "treat resupply as uncertain."),
    "greenhouse_dark": ("Plants need power too",
                        "Grow lights compete with life support during the night. "
                        "Leaving crops in the dark for days sets back weeks of growth."),
    "spe": ("Solar storms",
            "A solar particle event can deliver hundreds of mSv in hours, with "
            "only short warning. Shielding mass (regolith, water) and a storm "
            "shelter make the difference, and so does getting EVA crews inside."),
    "career_dose": ("Radiation adds up",
                    "NASA limits astronauts to 600 mSv over a whole career. Every "
                    "EVA and every day under thin shielding adds to that total."),
    "fatigue": ("Tired crews make mistakes",
                "Overworked astronauts have more accidents, especially on EVA. "
                "Rest schedules are a safety system, not a luxury."),
    "maintenance": ("Maintenance prevents failure",
                    "Equipment you don't maintain fails more often, and one "
                    "failure can cascade into others (no power, then no oxygen)."),
    "spares": ("Spare parts are life support",
               "Without spare parts, repairs are slow or impossible. Mission "
               "planners trade food and equipment mass against spares."),
    "micrometeorite": ("Micrometeoroids",
                       "With no atmosphere, tiny particles hit at around 20 km/s. "
                       "Regolith cover and hull maintenance reduce leaks."),
    "resupply_delay": ("Plan for delays",
                       "Launches slip and landers fail. Good plans keep enough "
                       "margin to survive a late resupply."),
    "loss": ("Every decision has a human cost",
             "A crew member was lost. Mission control reviews every decision "
             "chain that leads to a loss so future missions can avoid it."),
}

# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------
USE_COLOR = True


def _init_color(disabled: bool) -> None:
    global USE_COLOR
    if disabled or os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        USE_COLOR = False
        return
    if os.name == "nt":
        os.system("")  # enables ANSI escape codes on Windows 10+


def paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def red(t: str) -> str: return paint(t, "31;1")
def green(t: str) -> str: return paint(t, "32")
def yellow(t: str) -> str: return paint(t, "33")
def cyan(t: str) -> str: return paint(t, "36")
def bold(t: str) -> str: return paint(t, "1")
def dim(t: str) -> str: return paint(t, "2")


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        print("\n\nTransmission ended. Mission closed.")
        sys.exit(0)


def wrap(text: str, indent: str = "  ") -> str:
    return textwrap.fill(text, width=76, initial_indent=indent,
                         subsequent_indent=indent)


def bar(value: float, maximum: float, width: int = 12) -> str:
    frac = 0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
    filled = int(round(frac * width))
    text = "#" * filled + "." * (width - filled)
    if frac < 0.25:
        return red(text)
    if frac < 0.5:
        return yellow(text)
    return green(text)


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def rule(title: str = "") -> None:
    line = "=" * 78
    if title:
        title = f" {title} "
        start = (78 - len(title)) // 2
        line = line[:start] + title + line[start + len(title):]
    print(cyan(line))


# ---------------------------------------------------------------------------
# Game model
# ---------------------------------------------------------------------------
class Crew:
    def __init__(self, name: str, role: str, task: str):
        self.name = name
        self.role = role
        self.task = task
        self.health = 100.0
        self.fatigue = 10.0
        self.dose = 0.0
        self.alive = True
        self.over_limit = False


class Game:
    def __init__(self, site: dict, rng: random.Random):
        self.site = site
        self.rng = rng
        self.day = 1
        self.o2 = 150.0
        self.water = site["start_water"]
        self.food = 350.0
        self.parts = 12
        self.shield = 10.0
        self.science = 0.0
        self.morale = 75.0
        self.battery = 200.0
        self.gh_growth = 4
        self.has_shelter = False
        self.spe_warning = False
        self.low_batt_flag = False
        self.resupply_days = list(RESUPPLY_DAYS)
        self.outcome: str | None = None
        self.lessons: dict[str, int] = {}
        self.log: list[tuple[int, str]] = []
        self.stats = {
            "spe_count": 0, "blackout_days": 0, "failures": 0,
            "o2_made": 0.0, "food_grown": 0.0, "water_mined": 0.0,
            "eva_days": 0, "shed_days": 0,
        }
        self.systems = {
            "habitat": {"count": 1, "cond": 100.0},
            "solar": {"count": 4, "cond": 100.0},
            "battery": {"count": 3, "cond": 100.0},
            "reactor": {"count": 0, "cond": 100.0},
            "electrolyzer": {"count": 1, "cond": 100.0},
            "recycler": {"count": 1, "cond": 100.0},
            "greenhouse": {"count": 1, "cond": 100.0},
            "rover": {"count": 1, "cond": 100.0},
        }
        self.power_on = {k: True for k in TOGGLEABLE}
        self.crew = [
            Crew("Cmdr. Reyes", "Commander", "M"),
            Crew("Dr. Okafor", "Medic", "G"),
            Crew("Eng. Sato", "Engineer", "M"),
            Crew("Dr. Lindqvist", "Geologist", "X"),
        ]

    # ----- helpers -------------------------------------------------------
    def alive_crew(self) -> list[Crew]:
        return [c for c in self.crew if c.alive]

    def role_alive(self, role: str) -> bool:
        return any(c.alive and c.role == role for c in self.crew)

    def lesson(self, key: str) -> None:
        if key not in self.lessons:
            self.lessons[key] = self.day

    def note(self, text: str) -> None:
        self.log.append((self.day, text))

    def is_daylight(self, day: int) -> bool:
        night = self.site["night_days"]
        offset = 18 - night
        phase = (day - 1 + offset) % LUNAR_CYCLE
        return phase < LUNAR_CYCLE - night

    def days_until_change(self) -> int:
        now = self.is_daylight(self.day)
        d = self.day + 1
        while self.is_daylight(d) == now and d < self.day + LUNAR_CYCLE:
            d += 1
        return d - self.day

    def eff(self, key: str) -> float:
        s = self.systems[key]
        if s["count"] <= 0 or s["cond"] <= 0:
            return 0.0
        return 1.0 if s["cond"] >= 50 else 0.5 + s["cond"] / 100

    def battery_capacity(self) -> float:
        b = self.systems["battery"]
        return b["count"] * BATTERY_KWH * max(self.eff("battery"), 0.0)

    def generation(self, daylight: bool) -> float:
        g = 0.0
        if daylight:
            g += self.systems["solar"]["count"] * SOLAR_ARRAY_KWH * self.eff("solar")
        g += self.systems["reactor"]["count"] * REACTOR_KWH * self.eff("reactor")
        return g

    def power_demands(self, daylight: bool) -> list[tuple[str, float]]:
        """Loads in priority order: the first entries are powered first."""
        alive = self.alive_crew()
        eva = sum(1 for c in alive if TASKS[c.task][1] and c.task != "X")
        researchers = sum(1 for c in alive if c.task == "L")
        demands = [("habitat", HAB_BASE_KWH + (0 if daylight else HAB_NIGHT_HEAT_KWH))]
        if self.power_on["recycler"] and self.eff("recycler") > 0:
            demands.append(("recycler", RECYCLER_KWH * self.systems["recycler"]["count"]))
        if self.power_on["electrolyzer"] and self.eff("electrolyzer") > 0:
            demands.append(("electrolyzer",
                            ELECTROLYZER_KWH * self.systems["electrolyzer"]["count"]))
        if self.power_on["greenhouse"] and self.eff("greenhouse") > 0:
            demands.append(("greenhouse",
                            GREENHOUSE_KWH * self.systems["greenhouse"]["count"]))
        if eva and self.eff("rover") > 0:
            demands.append(("rover", ROVER_KWH_PER_EVA * eva))
        if researchers and self.power_on["lab"]:
            demands.append(("lab", LAB_KWH))
        return demands

    def leak_rate(self) -> float:
        return 0.3 + max(0.0, 40 - self.systems["habitat"]["cond"]) * 0.08

    def forecast(self, daylight: bool) -> dict:
        """Daily net change for the current plan (ignores random events)."""
        alive = self.alive_crew()
        n = len(alive)
        gen = self.generation(daylight)
        demands = self.power_demands(daylight)
        names = {name for name, _ in demands}
        o2_prod = 0.0
        if "electrolyzer" in names:
            o2_prod = (self.systems["electrolyzer"]["count"] * ELECTROLYZER_O2
                       * self.eff("electrolyzer"))
        rec = RECYCLER_EFF * self.eff("recycler") if "recycler" in names else 0.0
        ice = sum(self.site["ice_yield"] for c in alive if c.task == "I")
        gh_on = "greenhouse" in names
        water_net = (ice - WATER_PER_CREW * n * (1 - rec)
                     - o2_prod * WATER_PER_KG_O2
                     - (GREENHOUSE_WATER * self.systems["greenhouse"]["count"] if gh_on else 0))
        grown = 0.0
        if gh_on and self.gh_growth >= GREENHOUSE_GROW_DAYS:
            tend = min(2, sum(1 for c in alive if c.task == "G"))
            grown = (self.systems["greenhouse"]["count"] * GREENHOUSE_FOOD
                     * self.eff("greenhouse") * (1 + 0.4 * tend))
        return {
            "gen": gen,
            "demand": sum(k for _, k in demands),
            "o2_net": o2_prod - O2_PER_CREW * n - self.leak_rate(),
            "water_net": water_net,
            "food_net": grown - FOOD_PER_CREW * n,
        }

    # ----- daily simulation ---------------------------------------------
    def end_day(self) -> tuple[list[str], list[str]]:
        msgs: list[str] = []
        alerts: list[str] = []
        rng = self.rng
        daylight = self.is_daylight(self.day)
        alive = self.alive_crew()
        n = len(alive)
        deprived = False

        for c in alive:
            if c.fatigue >= 95 and c.task != "R":
                msgs.append(yellow(f"{c.name} is exhausted and collapses into a bunk (forced rest)."))
                c.task = "R"
                self.lesson("fatigue")
            if c.task == "S" and not self.has_shelter:
                c.task = "R"

        spe_today = self.spe_warning
        self.spe_warning = False

        # --- 1. Power --------------------------------------------------
        gen = self.generation(daylight)
        available = gen + self.battery
        powered: set[str] = set()
        shed: list[str] = []
        for name, kwh in self.power_demands(daylight):
            if kwh <= available + 1e-9:
                available -= kwh
                powered.add(name)
            else:
                shed.append(name)
        if "habitat" in shed:
            available = 0.0
            self.stats["blackout_days"] += 1
            self.lesson("blackout")
            alerts.append(red("BLACKOUT! The habitat lost power. Heat and air scrubbers failed overnight."))
            self.note("Habitat blackout")
            for c in alive:
                c.health -= 12
            self.morale -= 10
            deprived = True
        elif shed:
            self.stats["shed_days"] += 1
            self.lesson("load_shedding")
            msgs.append(yellow("Power shortfall. Automatically shut down: "
                               + ", ".join(shed) + "."))
        self.battery = clamp(available, 0.0, self.battery_capacity())

        cap = self.battery_capacity()
        low = cap > 0 and self.battery < 0.2 * cap
        if low and not self.low_batt_flag:
            alerts.append(yellow(f"Battery below 20% ({self.battery:.0f} kWh). Cut loads or expect shutdowns."))
        self.low_batt_flag = low

        # --- 2. Crew work ----------------------------------------------
        rover_factor = 1.0 if "rover" in powered else 0.25
        hand_digging = False
        for c in alive:
            t = c.task
            fat = 1.0 if c.fatigue < 70 else 0.6
            if TASKS[t][1]:
                self.stats["eva_days"] += 1
                self.systems["solar"]["cond"] -= 0.6  # abrasive dust tracked onto panels
            if t == "M":
                self._maintain(c, msgs)
            elif t == "I":
                mined = self.site["ice_yield"] * rover_factor * fat * rng.uniform(0.8, 1.2)
                self.water += mined
                self.stats["water_mined"] += mined
                hand_digging = hand_digging or rover_factor < 1
            elif t == "B":
                gain = 3.0 * rover_factor * fat
                self.shield = clamp(self.shield + gain)
                hand_digging = hand_digging or rover_factor < 1
            elif t == "L":
                if "lab" in powered:
                    self.science += 3.0 * self.site["science_mult"] * fat
                    if rng.random() < 0.03:
                        self._discovery(msgs, "lab analysis")
                else:
                    msgs.append(dim(f"{c.name} could not work: the lab has no power."))
            elif t == "X":
                skill = 1.5 if c.role == "Geologist" else 1.0
                self.science += 7.0 * self.site["science_mult"] * fat * skill
                if rng.random() < 0.06:
                    self._discovery(msgs, "geology survey")
        if hand_digging:
            msgs.append(yellow("The rover is offline, so EVA crews are digging by hand (75% slower)."))

        # --- 3. Oxygen -------------------------------------------------
        o2_made = 0.0
        if "electrolyzer" in powered:
            o2_made = (self.systems["electrolyzer"]["count"] * ELECTROLYZER_O2
                       * self.eff("electrolyzer"))
            if o2_made * WATER_PER_KG_O2 > self.water:
                o2_made = max(0.0, self.water / WATER_PER_KG_O2)
                msgs.append(yellow("Electrolyzer starved of water. Oxygen output reduced."))
            self.water -= o2_made * WATER_PER_KG_O2
        self.stats["o2_made"] += o2_made
        consumption = O2_PER_CREW * n
        self.o2 += o2_made - consumption - self.leak_rate()
        if self.o2 < 0:
            self.o2 = 0.0
            deprived = True
            self.lesson("oxygen")
            alerts.append(red("OXYGEN DEPLETED! The crew is suffering from hypoxia."))
            self.note("Oxygen ran out")
            for c in alive:
                c.health -= 25
        elif self.o2 < consumption * 5 and o2_made < consumption:
            alerts.append(red(f"Oxygen critical: about {self.o2 / max(consumption, 0.1):.1f} days left."))

        # --- 4. Water --------------------------------------------------
        gross = WATER_PER_CREW * n
        recovered = 0.0
        if "recycler" in powered:
            recovered = gross * RECYCLER_EFF * self.eff("recycler")
        elif n:
            self.lesson("recycler")
        gh_water = GREENHOUSE_WATER * self.systems["greenhouse"]["count"] if "greenhouse" in powered else 0.0
        self.water -= gross - recovered + gh_water
        if self.water < 0:
            self.water = 0.0
            deprived = True
            self.lesson("water")
            alerts.append(red("WATER EXHAUSTED! The crew is dehydrated."))
            self.note("Water ran out")
            for c in alive:
                c.health -= 20
        elif self.water < 60:
            alerts.append(yellow(f"Water reserve low: {self.water:.0f} kg."))

        # --- 5. Food ---------------------------------------------------
        grown = 0.0
        gh = self.systems["greenhouse"]
        if gh["count"] > 0:
            if "greenhouse" in powered:
                self.gh_growth = min(GREENHOUSE_GROW_DAYS, self.gh_growth + 1)
                if self.gh_growth >= GREENHOUSE_GROW_DAYS:
                    tend = min(2, sum(1 for c in alive if c.task == "G"))
                    grown = gh["count"] * GREENHOUSE_FOOD * self.eff("greenhouse") * (1 + 0.4 * tend)
            elif self.gh_growth > 0:
                self.gh_growth = max(0, self.gh_growth - 3)
                self.lesson("greenhouse_dark")
                msgs.append(yellow("Greenhouse lights are off and the plants are wilting. Growth set back."))
        self.food += grown
        self.stats["food_grown"] += grown
        need = FOOD_PER_CREW * n
        if self.food >= need:
            self.food -= need
        else:
            self.food = 0.0
            deprived = True
            self.lesson("food")
            alerts.append(red("FOOD RAN OUT. The crew is going hungry."))
            self.note("Food ran out")
            for c in alive:
                c.health -= 10
            self.morale -= 8

        # --- 6. Radiation ----------------------------------------------
        spe_base = 0.0
        if spe_today:
            spe_base = rng.uniform(100, 350)
            self.stats["spe_count"] += 1
            self.lesson("spe")
            alerts.append(red(f"SOLAR PARTICLE EVENT! Proton storm of {spe_base:.0f} mSv (unshielded) hits the base."))
            self.note(f"Solar storm ({spe_base:.0f} mSv unshielded)")
            self.systems["solar"]["cond"] -= 8
        inside_factor = 1 - 0.75 * self.shield / 100
        for c in alive:
            eva = TASKS[c.task][1]
            dose = GCR_SURFACE_DOSE * (1.0 if eva else inside_factor)
            if spe_today:
                if eva:
                    f = 1.0
                elif c.task == "S" and self.has_shelter:
                    f = 0.05
                else:
                    f = 0.5 - 0.42 * self.shield / 100
                dose += spe_base * f
                where = "on EVA" if eva else ("in the shelter" if f == 0.05 else "in the habitat")
                msgs.append(f"  {c.name} ({where}) received {dose:.0f} mSv.")
            c.dose += dose
            if dose > 100:
                c.health -= (dose - 50) / 3
                msgs.append(red(f"  {c.name} shows signs of acute radiation sickness."))
            if c.dose > CAREER_DOSE_LIMIT and not c.over_limit:
                c.over_limit = True
                self.lesson("career_dose")
                alerts.append(red(f"{c.name} has passed the {CAREER_DOSE_LIMIT:.0f} mSv career radiation limit."))
                self.note(f"{c.name} exceeded career dose limit")

        # --- 7. Fatigue, accidents, health ----------------------------
        medic = self.role_alive("Medic")
        for c in alive:
            eva = TASKS[c.task][1]
            if c.task == "R":
                c.fatigue -= 35
            elif c.task == "S":
                c.fatigue -= 10
            elif eva:
                c.fatigue += 22
            else:
                c.fatigue += 14
            c.fatigue = clamp(c.fatigue)
            if c.fatigue > 80:
                c.health -= 4
            if eva and rng.random() < 0.02 + (0.10 if c.fatigue > 75 else 0.0):
                hurt = rng.uniform(15, 30)
                c.health -= hurt
                self.lesson("fatigue")
                alerts.append(red(f"EVA ACCIDENT: {c.name} tore a suit glove and was injured (-{hurt:.0f} health)."))
                self.note(f"EVA accident: {c.name}")
            if not deprived:
                c.health += 1.0
                if c.task == "R":
                    c.health += 4.0
                if medic:
                    c.health += 1.5
            c.health = clamp(c.health)

        for c in alive:
            if c.health <= 0:
                c.alive = False
                c.health = 0.0
                self.morale -= 25
                self.lesson("loss")
                alerts.append(red(f"*** {c.name} ({c.role}) has died. ***"))
                self.note(f"{c.name} died")

        # --- 8. Morale -------------------------------------------------
        survivors = self.alive_crew()
        self.morale -= 0.6
        if self.role_alive("Commander"):
            self.morale += 0.4
        if survivors and not any(c.task == "R" for c in survivors):
            self.morale -= 1.5
        if survivors and sum(c.fatigue for c in survivors) / len(survivors) > 70:
            self.morale -= 2
        if grown > 0:
            self.morale += 0.6
        self.morale = clamp(self.morale)

        # --- 9. Equipment wear ----------------------------------------
        for key, s in self.systems.items():
            if s["count"] <= 0 or s["cond"] <= 0:
                s["cond"] = max(0.0, s["cond"])
                continue
            before = s["cond"]
            rate = rng.uniform(0.5, 1.8)
            if key == "habitat":
                rate *= 0.6
            elif key == "reactor":
                rate *= 0.4
            elif key == "battery" and not daylight:
                rate *= 1.3
            s["cond"] -= rate
            if s["cond"] < 35 and rng.random() < (35 - s["cond"]) / 120:
                s["cond"] -= rng.uniform(15, 30)
                self.stats["failures"] += 1
                self.lesson("maintenance")
                alerts.append(yellow(f"MALFUNCTION: {SYSTEM_LABELS[key]} failed under wear."))
            s["cond"] = clamp(s["cond"])
            if before > 0 and s["cond"] <= 0:
                alerts.append(red(f"{SYSTEM_LABELS[key]} has BROKEN DOWN. Repair needs 3 spare parts."))
                self.note(f"{SYSTEM_LABELS[key]} broke down")
        if self.systems["habitat"]["cond"] < 25:
            alerts.append(red(f"Habitat hull integrity at {self.systems['habitat']['cond']:.0f}%. It is leaking air."))

        # --- 10. Random events ----------------------------------------
        if rng.random() < 0.02:
            loss = rng.uniform(15, 40) * (1 - 0.5 * self.shield / 100)
            self.o2 = max(0.0, self.o2 - loss)
            self.systems["habitat"]["cond"] = clamp(self.systems["habitat"]["cond"] - 15)
            self.lesson("micrometeorite")
            alerts.append(yellow(f"MICROMETEOROID STRIKE! Hull punctured. {loss:.0f} kg of air vented before sealing."))
            self.note("Micrometeoroid strike")
        if rng.random() < 0.012:
            key = rng.choice([k for k, s in self.systems.items() if s["count"] > 0])
            self.systems[key]["cond"] = clamp(self.systems[key]["cond"] - 20)
            alerts.append(yellow(f"MOONQUAKE! The {SYSTEM_LABELS[key].lower()} was shaken and damaged."))
        if survivors and rng.random() < 0.015:
            c = rng.choice(survivors)
            c.health = clamp(c.health - 15)
            msgs.append(yellow(f"{c.name} has come down with an illness. Rest will help."))
        if rng.random() < 0.03:
            self.morale = clamp(self.morale + 6)
            msgs.append(green("A live video call with families on Earth lifts everyone's spirits."))
        if not spe_today and rng.random() < 0.035:
            self.spe_warning = True
            alerts.append(red("SOLAR FLARE DETECTED! Protons arrive TOMORROW. Bring EVA crews in "
                              "and use the storm shelter (task S) if you have one."))

        # --- 11. Advance the clock ------------------------------------
        if self.is_daylight(self.day + 1) != daylight:
            if daylight:
                self.lesson("night")
                alerts.append(cyan(f"SUNSET TOMORROW. Lunar night lasts {self.site['night_days']} days: solar power goes to zero."))
            else:
                alerts.append(green("SUNRISE TOMORROW. The solar arrays will come back online."))
        self.day += 1

        if not self.alive_crew():
            self.outcome = "lost"
        elif self.morale <= 0:
            self.outcome = "morale"
        elif self.systems["habitat"]["cond"] <= 0:
            self.outcome = "hull"
        elif self.day > MISSION_DAYS:
            self.outcome = "success"
        return msgs, alerts

    def _maintain(self, c: Crew, msgs: list[str]) -> None:
        skill = 1.5 if c.role == "Engineer" else 1.0
        candidates = [k for k, s in self.systems.items() if s["count"] > 0]
        worst = min(candidates, key=lambda k: self.systems[k]["cond"])
        s = self.systems[worst]
        label = SYSTEM_LABELS[worst]
        if s["cond"] <= 0:
            if self.parts >= 3:
                self.parts -= 3
                s["cond"] = 40 * skill
                msgs.append(green(f"{c.name} rebuilt the broken {label.lower()} (-3 parts)."))
            else:
                self.lesson("spares")
                msgs.append(red(f"{c.name} can't repair the {label.lower()}: it needs 3 spare parts."))
        elif self.parts >= 1:
            self.parts -= 1
            s["cond"] = clamp(s["cond"] + 35 * skill)
            msgs.append(dim(f"{c.name} serviced the {label.lower()} (now {s['cond']:.0f}%)."))
        else:
            self.lesson("spares")
            s["cond"] = clamp(s["cond"] + 8 * skill)
            msgs.append(yellow(f"{c.name} improvised repairs on the {label.lower()} with no spare parts."))

    def _discovery(self, msgs: list[str], source: str) -> None:
        bonus = 25 * self.site["science_mult"]
        self.science += bonus
        self.morale = clamp(self.morale + 5)
        msgs.append(green(f"DISCOVERY! The {source} turned up something remarkable (+{bonus:.0f} science)."))
        self.note(f"Scientific discovery ({source})")

    # ----- cargo ---------------------------------------------------------
    def cargo_menu(self, budget: int, title: str) -> None:
        order = {key: 0 for key, *_ in CARGO}
        while True:
            used = sum(order[k] * m for k, _, m, _, _ in CARGO)
            print()
            rule(title)
            print(f"  Mass budget: {budget} kg   Used: {used} kg   "
                  f"Remaining: {bold(str(budget - used))} kg\n")
            for i, (key, name, mass, mx, desc) in enumerate(CARGO, 1):
                unavailable = key == "shelter" and self.has_shelter
                qty = f"x{order[key]}" if order[key] else "  "
                line = f"  {i:>2}. {name:<20} {mass:>4} kg  {qty:<4} {desc}"
                print(dim(line + "  (already installed)") if unavailable else line)
            print(dim("\n  Type a number to add it ('7' or '1 3' for three), '-1' to remove one,"))
            print(dim("  or 'D' when the manifest is final."))
            cmd = ask("  Manifest> ").strip().lower()
            if cmd in ("d", "done"):
                break
            parts = cmd.split()
            if not parts:
                continue
            try:
                idx = int(parts[0])
                qty = int(parts[1]) if len(parts) > 1 else 1
            except ValueError:
                print(yellow("  Enter an item number, e.g. 3 or 3 2."))
                continue
            remove = idx < 0
            idx = abs(idx)
            if not 1 <= idx <= len(CARGO) or qty < 1:
                print(yellow("  No such item."))
                continue
            key, name, mass, mx, _ = CARGO[idx - 1]
            if remove:
                order[key] = max(0, order[key] - qty)
                continue
            if key == "shelter" and self.has_shelter:
                print(yellow("  You already have a storm shelter."))
                continue
            if mx is not None and order[key] + qty > mx:
                print(yellow(f"  You can only bring {mx} of those."))
                continue
            if used + mass * qty > budget:
                print(red(f"  Too heavy! That needs {mass * qty} kg and you have {budget - used} kg left."))
                continue
            order[key] += qty
        self._apply_cargo(order)

    def _add_hardware(self, key: str, qty: int) -> None:
        s = self.systems[key]
        old = s["count"]
        s["cond"] = (s["cond"] * old + 100.0 * qty) / (old + qty)
        s["count"] = old + qty

    def _apply_cargo(self, order: dict[str, int]) -> None:
        delivered = []
        for key, name, *_ in CARGO:
            q = order[key]
            if not q:
                continue
            delivered.append(f"{q}x {name}")
            if key == "food":
                self.food += 100 * q
            elif key == "parts":
                self.parts += 5 * q
            elif key == "oxygen":
                self.o2 += 80 * q
            elif key == "water":
                self.water += 200 * q
            elif key == "shelter":
                self.has_shelter = True
            else:
                if key == "greenhouse" and self.systems["greenhouse"]["count"] == 0:
                    self.gh_growth = 0
                self._add_hardware(key, q)
        if delivered:
            print(green("  Delivered: " + ", ".join(delivered)))
            self.note("Cargo delivered: " + ", ".join(delivered))
        else:
            print(dim("  Nothing delivered."))

    # ----- screens -------------------------------------------------------
    def dashboard(self) -> None:
        daylight = self.is_daylight(self.day)
        change = self.days_until_change()
        sky = (yellow(f"DAYLIGHT (sunset in {change} d)") if daylight
               else cyan(f"LUNAR NIGHT (sunrise in {change} d)"))
        print()
        rule(f"DAY {self.day}/{MISSION_DAYS}  |  {self.site['short']}")
        print(f"  {sky}", end="")
        if self.spe_warning:
            print("   " + red("!! SOLAR STORM ARRIVES TOMORROW !!"), end="")
        print("\n")

        fc = self.forecast(daylight)

        def runway(amount: float, net: float) -> str:
            sign = "+" if net >= 0 else ""
            text = f"net {sign}{net:.1f}/day"
            if net < 0:
                days = amount / -net
                col = red if days < 7 else (yellow if days < 20 else green)
                text += col(f"  (~{days:.0f} days left)")
            else:
                text += green("  (stable)")
            return text

        print(f"  OXYGEN  {self.o2:7.1f} kg  {bar(self.o2, 150)}  {runway(self.o2, fc['o2_net'])}")
        print(f"  WATER   {self.water:7.0f} kg  {bar(self.water, 1000)}  {runway(self.water, fc['water_net'])}")
        print(f"  FOOD    {self.food:7.0f} kg  {bar(self.food, 350)}  {runway(self.food, fc['food_net'])}")
        cap = self.battery_capacity()
        net = fc["gen"] - fc["demand"]
        net_txt = (green(f"+{net:.0f}") if net >= 0 else red(f"{net:.0f}"))
        print(f"  BATTERY {self.battery:7.0f} kWh {bar(self.battery, cap)}  "
              f"of {cap:.0f}  |  today: make {fc['gen']:.0f}, use {fc['demand']:.0f} ({net_txt} kWh)")
        print(f"  SHIELDING {self.shield:4.0f}%   PARTS {self.parts:3d}   SCIENCE {self.science:5.0f}   "
              f"MORALE {self.morale:3.0f}% {bar(self.morale, 100, 8)}"
              f"   SHELTER {'yes' if self.has_shelter else 'no'}")

        print(bold("\n  SYSTEMS"))
        keys = [k for k in SYSTEM_LABELS if self.systems[k]["count"] > 0]
        for i in range(0, len(keys), 2):
            cells = []
            for k in keys[i:i + 2]:
                s = self.systems[k]
                label = f"{SYSTEM_LABELS[k]} x{s['count']}"
                state = red(" BROKEN") if s["cond"] <= 0 else f" {s['cond']:3.0f}%"
                cells.append(f"  {label:<20}{bar(s['cond'], 100, 8)}{state}")
            print("   ".join(cells))
        toggles = "   ".join(
            f"{TOGGLE_LABELS[k]}: " + (green("ON") if self.power_on[k] else red("OFF"))
            for k in TOGGLEABLE)
        print(dim(f"  {toggles}"))
        if self.systems["greenhouse"]["count"]:
            if self.gh_growth >= GREENHOUSE_GROW_DAYS:
                print(dim("  Greenhouse crop: mature and harvesting"))
            else:
                print(dim(f"  Greenhouse crop: growing ({self.gh_growth}/{GREENHOUSE_GROW_DAYS} days)"))

        print(bold("\n  CREW") + dim("                                  health      fatigue     radiation"))
        for i, c in enumerate(self.crew, 1):
            if not c.alive:
                print(red(f"  {i}. {c.name:<14} {c.role:<10} DECEASED"))
                continue
            dose_txt = f"{c.dose:5.0f} mSv"
            if c.over_limit:
                dose_txt = red(dose_txt)
            elif c.dose > CAREER_DOSE_LIMIT * 0.66:
                dose_txt = yellow(dose_txt)
            print(f"  {i}. {c.name:<14} {c.role:<10} {TASKS[c.task][0]:<21}"
                  f"{bar(c.health, 100, 8)} {c.health:3.0f}  "
                  f"{bar(100 - c.fatigue, 100, 6)} {c.fatigue:3.0f}  {dose_txt}")
        print()

    def assign_menu(self) -> None:
        while True:
            print(bold("\n  ASSIGN CREW"))
            for i, c in enumerate(self.crew, 1):
                if c.alive:
                    print(f"   {i}. {c.name:<14} {c.role:<10} -> {TASKS[c.task][0]}"
                          f"  (fatigue {c.fatigue:.0f})")
            print(dim("\n   Tasks:"))
            for code, (label, eva) in TASKS.items():
                extra = {
                    "R": "recover fatigue and health",
                    "M": "fix the most worn system (uses 1 part, 3 if broken)",
                    "G": "boost greenhouse harvest by 40%",
                    "L": "safe indoor science (lab needs power)",
                    "S": "hide in the storm shelter (needs shelter)",
                    "I": f"+~{self.site['ice_yield']:.0f} kg water, needs rover power",
                    "B": "+3% regolith shielding, needs rover power",
                    "X": "big science, full radiation exposure",
                }[code]
                tag = yellow("[EVA]") if eva else "     "
                print(dim(f"    {code} {tag} {label:<22}") + dim(f" {extra}"))
            cmd = ask("\n   Enter '<crew#> <task>' (e.g. '3 I'), 'all R', or blank to finish: ").strip().upper()
            if not cmd:
                return
            parts = cmd.split()
            if len(parts) != 2 or parts[1] not in TASKS:
                print(yellow("   Format: crew number and task letter, e.g. 2 G"))
                continue
            who, task = parts
            if task == "S" and not self.has_shelter:
                print(yellow("   You don't have a storm shelter. Crew inside the habitat are protected by its shielding."))
                continue
            targets = self.alive_crew() if who == "ALL" else []
            if who != "ALL":
                if not who.isdigit() or not 1 <= int(who) <= len(self.crew) or not self.crew[int(who) - 1].alive:
                    print(yellow("   No such crew member."))
                    continue
                targets = [self.crew[int(who) - 1]]
            for c in targets:
                c.task = task

    def power_menu(self) -> None:
        while True:
            print(bold("\n  POWER MANAGEMENT"))
            print(dim("  When there isn't enough power, systems shut down in reverse order:"))
            print(dim("  habitat (never) > recycler > electrolyzer > greenhouse > rover > lab\n"))
            for i, k in enumerate(TOGGLEABLE, 1):
                state = green("ON ") if self.power_on[k] else red("OFF")
                kwh = {"recycler": RECYCLER_KWH * self.systems["recycler"]["count"],
                       "electrolyzer": ELECTROLYZER_KWH * self.systems["electrolyzer"]["count"],
                       "greenhouse": GREENHOUSE_KWH * self.systems["greenhouse"]["count"],
                       "lab": LAB_KWH}[k]
                print(f"   {i}. {TOGGLE_LABELS[k]:<24} {state}  {kwh:.0f} kWh/day")
            for label, dl in (("day", True), ("night", False)):
                fc = self.forecast(dl)
                net = fc["gen"] - fc["demand"]
                col = green if net >= 0 else red
                print(dim(f"   Lunar {label}: make {fc['gen']:.0f}, use {fc['demand']:.0f} -> ") + col(f"{net:+.0f} kWh/day"))
            cmd = ask("\n   Number to toggle, or blank to finish: ").strip()
            if not cmd:
                return
            if cmd.isdigit() and 1 <= int(cmd) <= len(TOGGLEABLE):
                k = TOGGLEABLE[int(cmd) - 1]
                self.power_on[k] = not self.power_on[k]

    def report(self) -> None:
        print()
        rule("MISSION REPORT")
        night = self.site["night_days"]
        day_fc, night_fc = self.forecast(True), self.forecast(False)
        night_deficit = max(0.0, night_fc["demand"] - night_fc["gen"])
        need = night_deficit * night
        cap = self.battery_capacity()
        print(bold("  Energy budget for one lunar night with the current plan"))
        print(f"    Night demand {night_fc['demand']:.0f} kWh/day - generation {night_fc['gen']:.0f} "
              f"= deficit {night_deficit:.0f} kWh/day")
        print(f"    x {night} night days = {need:.0f} kWh needed.  Battery capacity: {cap:.0f} kWh.")
        if need <= cap:
            print(green("    Your storage can carry this plan through the night."))
        else:
            print(red(f"    Shortfall of {need - cap:.0f} kWh: shut systems off at night or add power or storage."))
        print(f"    Daytime surplus for recharging: {day_fc['gen'] - day_fc['demand']:+.0f} kWh/day")

        print(bold("\n  Radiation"))
        inside = GCR_SURFACE_DOSE * (1 - 0.75 * self.shield / 100)
        print(f"    Inside the habitat: {inside:.2f} mSv/day.  On EVA: {GCR_SURFACE_DOSE:.2f} mSv/day.")
        print(f"    Solar storm protection: habitat blocks {50 + 42 * self.shield / 100:.0f}%"
              + (", shelter blocks 95%" if self.has_shelter else ", no storm shelter"))
        for c in self.alive_crew():
            print(f"    {c.name:<14} {c.dose:6.1f} mSv  {bar(CAREER_DOSE_LIMIT - c.dose, CAREER_DOSE_LIMIT, 10)}"
                  f"  {max(0, CAREER_DOSE_LIMIT - c.dose):.0f} mSv until career limit")

        upcoming = [d for d in self.resupply_days if d >= self.day]
        print(bold("\n  Logistics"))
        print(f"    Next resupply: " + (f"day {upcoming[0]}" if upcoming else "none scheduled"))
        print(f"    Mission ends after day {MISSION_DAYS} ({MISSION_DAYS - self.day + 1} days to go)")

        if self.lessons:
            print(bold("\n  Lessons learned so far"))
            for key in self.lessons:
                print(f"    - {LESSONS[key][0]}")
        ask(dim("\n  Press Enter to return..."))

    def help(self) -> None:
        print()
        rule("FLIGHT MANUAL")
        sections = [
            ("Goal", "Keep your crew alive and healthy for 90 days while collecting as much "
                     "science as possible. The mission fails if everyone dies, morale "
                     "collapses, or the habitat hull fails."),
            ("A day on the Moon", "Each turn is one Earth day. Assign every astronaut a task, "
                                  "set which systems get power, then advance the clock."),
            ("Power", "Solar arrays only work in sunlight. During the lunar night the base "
                      "runs on batteries (and a reactor if you have one). If power runs "
                      "short, systems shut down automatically, least critical first."),
            ("Air and water", "The electrolyzer splits water into oxygen, so it uses both water "
                              "and power. The recycler recovers 90% of used water. Ice-mining "
                              "EVAs refill your water tanks."),
            ("Food", "Greenhouses take 10 days to mature and need light every day. Tending "
                     "crops boosts the harvest. Leave the lights off and crops wilt."),
            ("Radiation", "Space radiation adds up every day, and EVAs give full exposure. "
                          "Build regolith shielding to cut indoor dose. When a solar flare "
                          "warning appears you have one day to get everyone inside."),
            ("Crew", "Work and EVAs build fatigue. Exhausted astronauts have accidents. The "
                     "Engineer repairs faster, the Geologist finds more science, the Medic "
                     "speeds healing, and the Commander keeps morale up."),
            ("Resupply", f"Landers arrive around days {RESUPPLY_DAYS[0]} and {RESUPPLY_DAYS[1]} "
                         f"with {RESUPPLY_BUDGET} kg each. Launches can slip."),
        ]
        for title, text in sections:
            print(bold(f"  {title}"))
            print(wrap(text, "    "))
        ask(dim("\n  Press Enter to return..."))

    # ----- main loop -----------------------------------------------------
    def handle_resupply(self) -> None:
        while self.resupply_days and self.day >= self.resupply_days[0]:
            scheduled = self.resupply_days.pop(0)
            if self.rng.random() < 0.15:
                new_day = self.day + 4
                self.resupply_days.insert(0, new_day)
                self.lesson("resupply_delay")
                self.note("Resupply delayed")
                print()
                print(red(f"  LAUNCH SCRUB: the day-{scheduled} lander was delayed. New arrival: day {new_day}."))
                ask(dim("  Press Enter..."))
                return
            print()
            print(green(f"  A cargo lander has touched down near the base (day {self.day})."))
            print(wrap("Mission Control asked you to choose its manifest weeks ago. "
                       "What did you request?"))
            self.cargo_menu(RESUPPLY_BUDGET, f"RESUPPLY MANIFEST  (day {self.day})")

    def play(self) -> None:
        while self.outcome is None:
            self.handle_resupply()
            self.dashboard()
            cmd = ask("  [A]ssign crew  [P]ower  [N]ext day  [F]ast-forward  [R]eport  [H]elp  [Q]uit > ").strip().upper()
            if cmd == "A":
                self.assign_menu()
            elif cmd == "P":
                self.power_menu()
            elif cmd in ("N", ""):
                self._advance(1)
            elif cmd.startswith("F"):
                raw = cmd[1:].strip() or ask("  Advance how many days? (stops early on alerts) [5]: ").strip()
                days = int(raw) if raw.isdigit() and int(raw) > 0 else 5
                self._advance(days)
            elif cmd == "R":
                self.report()
            elif cmd == "H":
                self.help()
            elif cmd == "Q":
                if ask(red("  Abort the mission and evacuate the crew? (y/n) ")).strip().lower() == "y":
                    self.outcome = "aborted"
                    self.note("Mission aborted by commander")
        self.debrief()

    def _advance(self, days: int) -> None:
        for i in range(days):
            day = self.day
            msgs, alerts = self.end_day()
            if msgs or alerts:
                print(dim(f"\n  --- End of day {day} ---"))
                for m in msgs:
                    print("  " + m)
                for a in alerts:
                    print("  " + a)
            if self.outcome:
                return
            resupply_due = self.resupply_days and self.day >= self.resupply_days[0]
            if alerts or resupply_due:
                if days > 1 and i < days - 1:
                    print(yellow("  Fast-forward paused so you can respond."))
                ask(dim("  Press Enter to continue..."))
                return

    # ----- end of mission -----------------------------------------------
    def debrief(self) -> None:
        survivors = self.alive_crew()
        print("\n")
        rule("MISSION DEBRIEF")
        banners = {
            "success": green("MISSION COMPLETE: the relief crew has arrived."),
            "lost": red("MISSION FAILED: the entire crew was lost."),
            "morale": red("MISSION FAILED: the crew lost confidence and demanded evacuation."),
            "hull": red("MISSION FAILED: the habitat hull failed and the base was evacuated."),
            "aborted": yellow("MISSION ABORTED: you ordered an emergency evacuation."),
        }
        print("  " + banners[self.outcome])
        last_day = min(self.day - 1, MISSION_DAYS)
        print(f"  Site: {self.site['name']}   Days completed: {last_day}/{MISSION_DAYS}\n")

        avg_health = sum(c.health for c in survivors) / len(survivors) if survivors else 0
        score = len(survivors) * 250 + int(self.science) + int(avg_health) * 3
        score += int(self.morale) * 2 + int(self.shield)
        score -= 150 * sum(1 for c in self.crew if c.over_limit)
        if self.outcome == "success":
            score += 1000
        else:
            score += last_day * 5
        score = max(0, score)

        print(bold("  Crew"))
        for c in self.crew:
            status = green("returned home") if c.alive else red("lost")
            flag = red("  over career limit") if c.over_limit else ""
            print(f"    {c.name:<14} {c.role:<10} {status:<24} dose {c.dose:6.1f} mSv{flag}")
        print(bold("\n  Statistics"))
        st = self.stats
        print(f"    Science collected     {self.science:8.0f} pts")
        print(f"    Oxygen produced       {st['o2_made']:8.0f} kg")
        print(f"    Food grown            {st['food_grown']:8.0f} kg")
        print(f"    Water mined from ice  {st['water_mined']:8.0f} kg")
        print(f"    Crew-days on EVA      {st['eva_days']:8d}")
        print(f"    Solar storms survived {st['spe_count']:8d}")
        print(f"    Equipment failures    {st['failures']:8d}")
        print(f"    Days with load-shed   {st['shed_days']:8d}")
        print(f"    Blackout days         {st['blackout_days']:8d}")
        print(f"    Final shielding       {self.shield:7.0f}%")
        print(f"    Final morale          {self.morale:7.0f}%")

        if self.outcome == "success":
            grade = ("A  Model outpost" if score >= 3400 else
                     "B  Strong command" if score >= 3000 else
                     "C  Mission accomplished, lessons to learn" if score >= 2500 else
                     "D  Survived, barely")
        else:
            grade = "F  Mission failure"
        print(bold(f"\n  FINAL SCORE: {score}    GRADE: {grade}"))

        if self.log:
            print(bold("\n  Key events"))
            for day, text in self.log[-14:]:
                print(f"    Day {day:>2}: {text}")

        if self.lessons:
            print(bold("\n  What this mission taught you"))
            for key, day in self.lessons.items():
                title, text = LESSONS[key]
                print(cyan(f"  > {title} (first seen day {day})"))
                print(wrap(text, "    "))
        print(bold("\n  Questions for discussion"))
        for q in (
            "Which single decision most affected the outcome of your mission, and why?",
            "Where did solving one problem create another (for example, more oxygen meant less water)?",
            "How would your cargo choices change if you flew this mission again?",
            "Which site would you recommend for the first permanent lunar base? Defend your choice.",
        ):
            print(wrap("- " + q, "    "))
        print()
        rule()


# ---------------------------------------------------------------------------
# Start-up
# ---------------------------------------------------------------------------
TITLE = r"""
   _                            ___        _                    _
  | |   _  _ _ _  __ _ _ _     / _ \ _  _| |_ _ __  ___ ___ __| |_
  | |__| || | ' \/ _` | '_|   | (_) | || |  _| '_ \/ _ (_-<|_ /  _|
  |____|\_,_|_||_\__,_|_|      \___/ \_,_|\__| .__/\___/__/ /__|\__|
                                              |_|  ARTEMIS BASE CAMP
"""


def choose_site(preset: str | None) -> dict:
    if preset in SITES:
        return SITES[preset]
    print(bold("\n  Choose your landing site:\n"))
    for key, s in SITES.items():
        print(f"  {key}. {bold(s['name'])}  [{s['difficulty']}]")
        print(wrap(s["desc"], "     "))
        print(dim(f"     Night: {s['night_days']} days | Ice per EVA: ~{s['ice_yield']:.0f} kg | "
                  f"Science x{s['science_mult']} | Starting water: {s['start_water']:.0f} kg\n"))
    while True:
        choice = ask("  Site (1-3)> ").strip()
        if choice in SITES:
            return SITES[choice]


def briefing(game: Game) -> None:
    s = game.site
    print()
    rule("PRE-LAUNCH BRIEFING")
    print(wrap(f"You are landing at {s['name']}. Your crew of four must survive "
               f"{MISSION_DAYS} days until the relief crew arrives."))
    print()
    print(wrap("Your base already includes: 1 habitat, 4 solar arrays (120 kWh/day in "
               "sunlight), 3 battery banks (300 kWh), 1 electrolyzer, 1 water recycler, "
               "1 greenhouse, 1 excavator rover, 150 kg O2, 350 kg food, "
               f"{s['start_water']:.0f} kg water and 12 spare parts."))
    print()
    night_need = (HAB_BASE_KWH + HAB_NIGHT_HEAT_KWH + RECYCLER_KWH + ELECTROLYZER_KWH
                  + GREENHOUSE_KWH + LAB_KWH)
    total = night_need * s["night_days"]
    print(wrap(f"Engineering note: with everything switched on, the base uses about "
               f"{night_need:.0f} kWh per day at night. A {s['night_days']}-day night needs "
               f"{total:.0f} kWh, and your batteries hold 300 kWh."))
    print()
    print(wrap("Your crew uses about 3.4 kg of oxygen, 7.2 kg of food and 16 kg of water "
               "a day. 150 kg of oxygen lasts about 44 days without the electrolyzer."))
    print()
    print(wrap(f"You may add {INITIAL_CARGO_BUDGET} kg of extra cargo to the launch. "
               "Every kilogram counts. Choose carefully."))
    game.cargo_menu(INITIAL_CARGO_BUDGET, "LAUNCH MANIFEST")
    print()
    print(wrap("Tip: press H at any time for the flight manual and R for a full report "
               "on whether your power plan will survive the next night."))
    ask(dim("\n  Press Enter to land..."))


def main() -> None:
    parser = argparse.ArgumentParser(description="Lunar Outpost: a lunar base survival game.")
    parser.add_argument("--seed", type=int, help="random seed for a repeatable mission")
    parser.add_argument("--site", choices=list(SITES), help="skip site selection (1, 2 or 3)")
    parser.add_argument("--no-color", action="store_true", help="disable colored output")
    args = parser.parse_args()
    _init_color(args.no_color)

    print(cyan(TITLE))
    print(wrap("The year is 2032. The first long-duration lunar outpost is ready for its "
               "crew. Every choice you make (who works, who rests, what gets power, what "
               "gets launched) decides whether they come home."))
    rng = random.Random(args.seed)
    site = choose_site(args.site)
    game = Game(site, rng)
    briefing(game)
    game.play()


if __name__ == "__main__":
    main()
