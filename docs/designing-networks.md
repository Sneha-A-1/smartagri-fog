# Designing networks and workloads

## Topology designer

**Topology designer** in the sidebar lists your saved networks. **New topology** opens the designer:

| To do this | Do this |
| --- | --- |
| Start from a farm network | **Generate farm network**: choose farms, gateways, edge devices, fog and cloud servers |
| Add a device | Click **IoT gateway**, **Edge device**, **Fog server** or **Cloud server** |
| Connect two devices | **Connect nodes**, then click the first device and the second. **Esc** stops connecting |
| Edit a device or link | Click it; edit its properties on the right |
| Delete | Select it and press **Delete**, or click **Delete selected** |
| Tidy the drawing | **Arrange by layer** (cloud at the top, gateways at the bottom) and **Fit to screen** |
| Share or back up | **Export** downloads JSON; **Import** loads one |

The panel on the right checks the network as you edit it: every gateway must be able to reach a device that can
compute. "Ready to simulate" means it is valid.

Link technologies (Wi-Fi, 4G, 5G, LoRaWAN, Zigbee, BLE, NB-IoT, Ethernet, WAN) fill in typical bandwidth and
latency values. These are rough starting points, not measurements: set real values from your own measurements or
from published studies, and cite them.

Researcher mode adds cost and failure settings (mean time between failures and repair time) for each device.

## Workloads

**Simulation** → **New workload** starts from the agricultural task mix. Each task type has a priority, an arrival
rate per gateway, a processing length (million instructions), input and output data sizes, memory, a deadline, and
whether the result goes back to the gateway (to drive an actuator) or is only stored.

**Expected load** shows tasks per hour and the average compute demand. Choose a topology to see that demand as a
share of total capacity. Above about 85%, queues grow quickly.

## Running

- **Simulation** → *Run a simulation*: one run of one policy, for exploring behaviour. The job page shows every
  metric and a per-device table.
- **Experiments** → *My saved network and workload*: proper comparisons with replications and statistics. The
  experiment stores its own copy of the network and workload, so later edits to the saved versions don't change
  its results.
