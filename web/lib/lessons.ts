import type { HabitatSlug } from "@/lib/types";

export type LessonLink = { label: string; href: string };

export type Lesson = {
  id: "apollo_1" | "apollo_13" | "mir_1997";
  year: string;
  date: string;
  title: string;
  setting: string;
  atmosphere: string;
  happened: string;
  changed: string;
  dataSays: string;
  insightIds: string[]; // pulled live from /insights
  habitat?: HabitatSlug; // where the insight chips link on the Mission brief
  links: LessonLink[];
  ask: string; // prefilled on /ask, never auto-sent
};

export const LESSONS: Lesson[] = [
  {
    id: "apollo_1",
    year: "1967",
    date: "27 January 1967",
    title: "Apollo 1",
    setting: "Launch pad test, Cape Kennedy",
    atmosphere: "100% O2 at 16.7 psia (115 kPa)",
    happened:
      "During a ground test with the crew sealed inside, a fire started in the command module and spread through the pure oxygen cabin in seconds. Astronauts Gus Grissom, Ed White and Roger Chaffee died.",
    changed:
      "NASA redesigned the spacecraft: flammable cabin materials were replaced, the hatch was made to open quickly, and the cabin switched to a 60% oxygen, 40% nitrogen mix on the launch pad.",
    dataSays:
      "No ISS combustion test comes anywhere near Apollo 1's atmosphere: the highest ambient oxygen tested is 40%. Even well below pure oxygen, the data shows oxygen-rich flames refuse to go out on their own.",
    insightIds: ["cfig_high_o2_persistence", "coverage_gap"],
    habitat: "lunar",
    links: [{ label: "See Apollo 1 on the coverage chart", href: "/?habitat=apollo1" }],
    ask: "What do the ISS tests say about flames at high oxygen levels?",
  },
  {
    id: "apollo_13",
    year: "1970",
    date: "13 April 1970",
    title: "Apollo 13",
    setting: "Service module, on the way to the Moon",
    atmosphere: "Inside a pressurized liquid oxygen tank",
    happened:
      "Damaged wiring inside an oxygen tank ignited, and the tank failed about 56 hours into the mission. The crew used the lunar module as a lifeboat and returned safely on 17 April.",
    changed:
      "The oxygen tanks were redesigned to remove the wiring and materials that could burn inside them, and an extra oxygen supply was added to later missions.",
    dataSays:
      "This one is outside the data. None of the 18 ISS investigations burned materials inside a pressurized oxygen system, so IgnitIQ will not stretch a finding to cover it. It is a reminder that oxygen hardware itself is a fire source.",
    insightIds: [],
    links: [],
    ask: "Do any ISS experiments cover fires inside oxygen tanks?",
  },
  {
    id: "mir_1997",
    year: "1997",
    date: "23 February 1997",
    title: "Mir fire",
    setting: "Mir space station, six crew aboard",
    atmosphere: "Station air, near sea-level pressure",
    happened:
      "A solid-fuel oxygen generator, an \"oxygen candle\", caught fire. Thick smoke filled the station while the crew put on masks and fought the flames with extinguishers until it burned out.",
    changed:
      "The fire showed that smoke spreads and lingers in microgravity, that crews need reliable masks and suppression, and that the hardware making oxygen can itself start a fire.",
    dataSays:
      "ISS experiments now study both halves of that problem: SAME and SAME-R measured smoke from overheated materials in microgravity to improve smoke detectors, and FLEX tested which inert gases put flames out.",
    insightIds: ["flex_diluent_extinction"],
    habitat: "iss",
    links: [{ label: "Explore the SAME-R smoke tests", href: "/experiments?psi=PSI-101" }],
    ask: "What did ISS experiments learn about smoke and suppressants in microgravity?",
  },
];