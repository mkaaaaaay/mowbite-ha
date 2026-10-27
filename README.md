# MowBite for OpenMower

A Home Assistant integration that brings an [OpenMower](https://github.com/ClemensElflein/OpenMower) robot mower
into Home Assistant, with the map and the look of [MowBite](https://github.com/mkaaaaaay/mowbite). It talks to the
mower's MQTT broker directly, no cloud and no extra add-on.

![The MowBite card in Home Assistant](images/card.png)

## What it does

- **The mower in Home Assistant**: a lawn mower entity with start, pause and go home, so Home Assistant's own
  mower controls work with it. Start goes on where a paused mow stopped.
- **Sensors**: battery, state, GPS quality and accuracy, battery voltage, mow motor temperature, and more that
  are off by default (charge voltage and current, motor controller temperatures, mow motor current and speed).
  Emergency stop, charging, rain and whether the GPS has a fix as binary sensors. With the MowBite address set and
  a MowBite that works out its own battery level, the battery is that one: it stays put when the mower sets off
  (OpenMower's drops by a fifth from the voltage alone) and is at 0 % where OpenMower sends the mower home.
- **Where the mower is**: a GPS tracker (`device_tracker`) from its map position and the GPS datum, for zones in
  automations ("when the mower enters the front garden") and the Home Assistant map. It updates at most every 10 s
  while the mower moves.
- **Docked or on the lawn**: from Home Assistant 2026.10 on, a mower that stands still outside the dock shows as
  idle, not as docked, so an automation for "docked" only fires in the dock.
- **Buttons** for skipping an area and for resetting an emergency stop. The reset is off by default, an
  emergency stop has a reason out at the mower.
- **How far it got**: the area being mowed, how far through it is, the last problem the mower had (a docking
  retry, GPS lost, an emergency stop) and the lawn's area.
- **Only what your mower has**: the entities below come once the mower or the app first provides the data, and
  stay after that, also while the mower is off for the winter. None of them shows that your mower can't do. (The
  sensors above are always there, one your OpenMower doesn't report stays unavailable, the charge current with
  `ignore_charging_current` for example.)
  - Skip the rest of a path, drop an interrupted job (newer OpenMower)
  - The time left for the area and the whole job, how long mowing all areas takes, the area left uncut after a
    job with a button to mow just that, the place where the mower came closest to an edge, and the planning
    settings (fill pattern, outline loops, mow the leftovers by itself and more), changed only while the mower is
    idle (with the MowBite Planner on the mower)
  - The MowBite version, the mower computer's CPU temperature, free memory and storage, whether the schedule is
    on, its last start and the last start it left out (rain, dark, battery low, ...), and the longest blade time
    on one charge in the last 30 days, which gets shorter as the battery ages (with the MowBite address set)
  - Off at first, switch them on if you like (with the MowBite address set): the Wi-Fi signal, the next scheduled
    start, the schedule as a calendar, the blade time, the distance driven with the blade on and in all and the runs,
    in total and today, and when the blades and the cleaning are due again, as hours left and as a yes/no for
    reminders
  - Also off at first, they change something in MowBite the way its own pages do and nothing else: buttons for
    blades changed and cleaned, after how many blade hours each is due again, and the schedule's on/off, skipping
    it when it rains or rain is forecast, the battery level it starts from, skipping today and ending a pause (the
    rest of the schedule stays as it is)
- **Events** for automations and notifications: all areas done, heading home (with the reason: battery, rain,
  mow motor too hot or sent home), docked, left the dock, docking retry, docking or undocking failed,
  navigation error, mow motor didn't start, GPS lost while mowing, emergency stop and cleared, fully charged,
  job dropped, mower started, shut down. Each comes with a message in Home Assistant's language.
- **Push notifications** with the blueprint below: pick your phone and the events, every message has buttons to
  snooze for an hour or until the next morning. A switch pauses them as long as you like.
- **The MowBite card**: the mower like on MowBite's dashboard, its status, the buttons and the map with the
  areas, obstacles, the docking station, the mower and its track. On wide screens side by side, on phones one
  below the other. It comes with the integration, no resource to add.
- **Map colours and icons from MowBite**: with the address of your MowBite container set, the map uses the
  colours, icons and icon sizes you picked in the app, and its garden style with the pictures picked for each area.
  Without it a card can have the garden style too, the pictures then go by the areas' names (an area called "tree"
  or "Baum" gets a tree, "table" a table, "parasol" a parasol). MowBite's decorations, areas that are only a
  picture (the beds round the lawn the mower never reaches), are drawn like obstacles, and pictures set by
  themselves (a grill, a heater) where they stand. The integration leaves both out.
- **The mower at its real size**: with the mower's sizes known the map draws its outline with the blade, and along
  the track the strip the blade really cut.
- **What's still to mow**: while mowing, the map shows the rest of the area's plan as a thin dashed line, after a
  job what was left uncut and the places the mower came too close to an edge.

![The card on a phone](images/phone.png)

What it reads is what OpenMower publishes on MQTT: `robot_state`, `actions`, `sensors`, `events`,
`position` and `map`, and over the mower's rpc its plans and event history, asked when something changes (an area
starts, the mower docks, the map changes), never polled. The track of a job that was already running when Home
Assistant started comes from the mower's position history (OpenMower 1.3 and newer). An emergency stop is told
once it has lasted 10 seconds, like MowBite's own notifications do it, and a navigation error only when the mower
doesn't head home right after it (OpenMower reports one when it's sent home in the middle of a path).

### Which OpenMower

- **1.0.2 and newer**: the mower, its sensors and the map.
- **1.1.1**: the GPS tracker (it needs the GPS datum OpenMower publishes from then on).
- **1.3.0**: the mower moving on the map and its track, the events, the runs of the day and the track of a job
  that was already running when Home Assistant started.
- **1.4.0**: the event for a mow motor that didn't start.
- **Current edge** (not in a release yet): dropping an interrupted job, how far through the area and the lanes
  left without the MowBite Planner, and the reason for an emergency stop without the MowBite address.

## Install

You need Home Assistant 2026.9 or newer and the MQTT broker on your mower reachable from Home Assistant
(port 1883).

**With HACS** (recommended): MowBite for OpenMower is in HACS' default list. Search for it in HACS, download it
and restart Home Assistant, or open it in your HACS directly:

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mkaaaaaay&repository=mowbite-ha&category=integration)

**By hand**: copy `custom_components/mowbite` into the `custom_components` folder of your Home Assistant
configuration and restart.

## Set up

Settings, Devices & services, Add integration, MowBite for OpenMower:

- **Broker host**: usually the mower itself, `openmower` or its IP address. **Port** 1883.
- **Topic prefix**: empty on the mower's own broker. Only if your OpenMower publishes behind a prefix, for
  example `openmower/` when it's bridged to another broker.
- **Username and password**: only if your broker has a login.

It checks that a mower answers before it saves. Several mowers work too, each is its own entry.

Under **Configure** on the integration:

- **MowBite address**: where your MowBite container runs, for example `http://openmower:8082`. Optional, without
  it the map is always shown, plain, with MowBite's default colours and icons. A card can still have the garden
  style (`map_style: garden`).
- **Show the map**: when the cards show the map, as set in the MowBite app (always without a MowBite address),
  only while the mower drives, always or never. A card can still have its own setting.
- **Mower sizes**: for the mower's outline and the strip its blade cuts on the map. Pick your mower, or Own sizes
  for a form like the one in the MowBite app (in cm, from the middle between the rear drive wheels). Sizes set in
  the MowBite app come first, then the ones the MowBite Planner has, then these.

## The card

Edit a dashboard, add a card and search for MowBite for OpenMower. Its editor (German or English, like Home
Assistant) lists the mower's values to tick for the status, the ones from the MowBite app marked so, and takes any
other entity too. In YAML:

```yaml
type: custom:mowbite-card
entity: lawn_mower.openmower
map: integration   # integration, app, auto (while it drives), always or never
map_style: app     # app (as set in MowBite), plain or garden
map_height: 260    # pixels, leave it out for a square map like in the app
status: true       # false shows only the map
today: true        # false leaves out "Today" (what was mowed, the last runs, the next start)
leftovers: true    # false leaves out checking the last mow for leftovers (with the MowBite Planner)
theme: frost       # frost (frosted glass), aurora, sunny, openmower, dark, light or auto (like Home Assistant)
blur: true         # false is lighter for older tablets: no blur, and the map follows the mower in steps
entities:          # more values in the status, any Home Assistant entity, a tap opens it
  - sensor.openmower_position_accuracy
  - entity: sensor.openmower_area_time_left
    name: Time left
hide:              # what the status leaves out: gps, speed, progress, charging, battery, rain, wifi, temperatures
  - temperatures
```

The card is MowBite's dashboard: the status with the battery ring, the facts (GPS, speed, progress with the time
left, Wi-Fi, temperatures, and the entities you add), the buttons, the map, and "Today" with what was mowed, the
last runs, a start the schedule left out, maintenance due and the next start. In the language of your Home
Assistant user, German or English, with MowBite's own words. Like in the app some buttons only show when they're
of use: "Skip this path" while the mower mows, "Reset emergency" while an emergency stop is on.

It draws the map the way your MowBite does: its colours, the mower and dock icon, the garden style with the pictures
picked for the areas, the real edges and the mower's outline. With the MowBite address set and a MowBite that serves
its pictures (1.4.0-beta.7 and newer) the card takes them from the mower, so it looks like the MowBite the mower
runs, else the ones that came with the integration. The mower's pictures run in a sandbox of their own, they can't
reach Home Assistant.

![The map in the garden style while the mower drives](images/map.png)

The garden the card worked out is kept in the browser, so it's there right away the next time the page opens, and
worked out again only when the map or the looks change. While it's on its way the map shows only its outlines.

The map zooms with the buttons, the mouse wheel or two fingers, and moves when dragged. While the mower drives the
map follows it like the app's overview: a few metres around the mower, with the mower gliding in the middle.
Zooming changes how much is shown around it, dragging the map stops following, the target button starts it
again.

## Notifications

The blueprint comes with the integration: after installing and restarting it's under Settings, Automations &
scenes, Blueprints. One you imported by hand before stays as it is. By hand, Import blueprint:

```
https://github.com/mkaaaaaay/mowbite-ha/blob/main/blueprints/automation/mowbite/notify.yaml
```

Make an automation from it, pick the mower's events entity, your phone (with the Home Assistant app) and the
events you want to hear about. Errors come through as time-sensitive on iOS and with high priority on
Android.

## Troubleshooting

- **The card says "configuration error" right after installing**: reload the page once. The browser still has
  the page from before the integration was there.
- **Dashboards in YAML mode**: add `/mowbite/mowbite-card.js` as a JavaScript module resource yourself, the
  integration only adds it to dashboards Home Assistant keeps.
- **The mower is unavailable**: check the broker host and port, and the prefix. The integration keeps trying,
  a mower that's off (winter, shed) isn't an error.
- **"MowBite doesn't answer" under Repairs**: the MowBite address set under Configure didn't answer for 10 minutes
  while the mower did. MowBite usually runs on the mower on port 8082, for example `http://openmower:8082`.
- **Asking for help or reporting a bug**: on the integration's page, the three dots, Download diagnostics, and attach
  the file. It has what the mower and MowBite told the integration, without logins and without where your garden
  is.

## Development

The tests run against Home Assistant's own test tools:

```
pip install -r requirements_test.txt
pytest
```

The card's pictures (`mowbite-art.js`) and its dashboard logic and looks (`mowbite-app.js`) are built from
MowBite's own sources:

```
node scripts/build-art.mjs <path to MowBite>
```

## License

GPL-3.0, like MowBite.
