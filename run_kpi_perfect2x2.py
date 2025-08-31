import os, sys, csv, argparse, math, random
from statistics import mean

def sumo_bin(name):
    sh = os.environ.get("SUMO_HOME")
    return os.path.join(sh, "bin", name) if sh else name

def tou_price(offset_sec=0):
    """ToU: Peak=0.40 (7–10,17–20), Off-peak=0.20 (22–6), Else=0.30"""
    def f(t):
        tt = t + offset_sec
        h = int((tt // 3600) % 24)
        if 7 <= h < 10 or 17 <= h < 20: return 0.40
        if h >= 22 or h < 6:            return 0.20
        return 0.30
    return f

def read_csv_series(path):
    if not os.path.isfile(path): return []
    with open(path, newline="", encoding="utf-8") as f:
        return [{k.lower(): v for k, v in r.items()} for r in csv.DictReader(f)]

def soc_ratio(traci, vid, cap_kwh=50.0, fallback_if_unknown=True):
    """SOC ratio in [0,1]; prefer actualCharge/Capacity (Wh), else soc (ratio/Wh), else 0."""
    try:
        chg = traci.vehicle.getParameter(vid, "device.battery.actualBatteryCharge")
        cap = traci.vehicle.getParameter(vid, "device.battery.actualBatteryCapacity")
        if chg and cap:
            chg = float(chg); cap = float(cap)
            if cap > 0: return max(0.0, min(1.0, chg / cap))
    except: pass
    try:
        soc = traci.vehicle.getParameter(vid, "device.battery.soc")
        if soc:
            v = float(soc)
            if v <= 1.0:   return max(0.0, min(1.0, v))
            cap_Wh = cap_kwh * 1000.0
            return max(0.0, min(1.0, v / cap_Wh))
    except: pass
    return 0.0 if fallback_if_unknown else None

def estimate_wait_hours(queue_len, soc, capacity_kwh, power_kw,
                        target_soc=0.8, min_h=10/60, max_h=45/60):
    need_kwh = max(0.0, (target_soc - soc)) * capacity_kwh
    service_h = min(max_h, max(min_h, need_kwh / max(1e-6, power_kw)))
    return queue_len * service_h

def accept_prob_logit(soc, price, wait_h, beta0, beta1, beta2, beta3,
                      p_ref=0.30, p_span=0.10):
    price_norm = (price - p_ref) / p_span
    z = beta0 + beta1 * (1.0 - soc) + beta2 * price_norm + beta3 * wait_h
    return 1.0 / (1.0 + math.exp(-max(-20, min(20, z))))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gui", action="store_true")
    ap.add_argument("--strategy", choices=["flat","tou","ppo_csv","ppo_time"], required=True)
    ap.add_argument("--routes", default="ev_routes_ev_600.rou.xml")
    ap.add_argument("--additional", default="additional_stop.add.xml")
    ap.add_argument("--csv", default="ev_users_with_pricing_action.csv")
    ap.add_argument("--base", type=float, default=0.30)
    ap.add_argument("--spread", type=float, default=0.30)
    ap.add_argument("--period", type=float, default=120.0, help="PPO-Time period (s)")
    ap.add_argument("--start-h", type=int, default=21)
    ap.add_argument("--start-min", type=int, default=0)
    ap.add_argument("--cap-kwh", type=float, default=50.0)
    ap.add_argument("--target-soc", type=float, default=0.70)
    ap.add_argument("--soc-thres", type=float, default=0.30)
    
    ap.add_argument("--beta0", type=float, default=-1.8)
    ap.add_argument("--beta1", type=float, default= 3.8)
    ap.add_argument("--beta2", type=float, default=-7.0)
    ap.add_argument("--beta3", type=float, default=-6.0)
    
    ap.add_argument("--cooldown", type=float, default=90.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="kpi_perfect2x2.csv")
    args = ap.parse_args()

    random.seed(args.seed)
    import traci

    here = os.path.abspath(os.path.dirname(__file__))
    net  = os.path.join(here, "ev_map.net.xml")
    routes = os.path.join(here, args.routes)
    additional = os.path.join(here, args.additional)

    cmd = [sumo_bin("sumo-gui" if args.gui else "sumo"),
           "-n", net, "-r", routes, "--additional-files", additional]
    print("Launching:", " ".join(cmd))
    traci.start(cmd)

    
    stations = {}
    for cs in traci.chargingstation.getIDList():
        stations[cs] = {
            "lane":  traci.chargingstation.getLaneID(cs),
            "start": float(traci.chargingstation.getStartPos(cs)),
            "end":   float(traci.chargingstation.getEndPos(cs)),
            "power_kw": 50.0,
        }

    util = {cs: 0 for cs in stations}
    rev  = {cs: 0.0 for cs in stations}
    totalP = []
    step = 0

    price_series = []   

    offset_sec = args.start_h * 3600 + args.start_min * 60
    touf = tou_price(offset_sec)
    series = read_csv_series(os.path.join(here, args.csv)) if args.strategy in ("ppo_csv","ppo_time") else []
    assigned = set()
    last_accept = {cs: -1e9 for cs in stations}  
    prev_charge_price = args.base                 

    
    def price_at(t, step, prev_charge):
        
        if args.strategy == "flat":
            raw = args.base
        elif args.strategy == "tou":
            raw = touf(t)  
        else:
            if not series: raw = args.base
            else:
                idx = min(step//10, len(series)-1) if args.strategy=="ppo_csv" else min(int(t//args.period), len(series)-1)
                raw = args.base + args.spread * float(series[idx].get("recommended_action_value", series[idx].get("action_value","0") or 0))
        
        decision = 0.40 if raw >= 0.35 else (0.20 if raw <= 0.25 else 0.30)
        
        capped = max(0.20, min(0.40, raw))
        charge = 0.95 * prev_charge + 0.05 * capped
        return decision, charge

    while traci.simulation.getMinExpectedNumber() > 0 and step < 7200:
        traci.simulationStep()
        t = traci.simulation.getTime()
        decision_price, charge_price = price_at(t, step, prev_charge_price)
        prev_charge_price = charge_price

        price_series.append((t, decision_price, charge_price))  

        for cs, meta in stations.items():
            lane = meta["lane"]; s = meta["start"]; e = meta["end"]; pkw = meta["power_kw"]
            vids = traci.lane.getLastStepVehicleIDs(lane)
            queue_len = sum(1 for vid0 in vids
                            if s <= traci.vehicle.getLanePosition(vid0) <= e
                            and traci.vehicle.getSpeed(vid0) < 0.1)
            for vid in vids:
                if vid in assigned: continue
                vpos = traci.vehicle.getLanePosition(vid)
                if vpos < s:

                    if t - last_accept[cs] < args.cooldown:
                        continue
                    soc = soc_ratio(traci, vid, cap_kwh=args.cap_kwh, fallback_if_unknown=True)
                    if soc > 1.0: soc = 1.0
                    if soc > args.soc_thres: continue
                    wait_h = estimate_wait_hours(queue_len, soc, args.cap_kwh, pkw, target_soc=args.target_soc)

                    
                    acc_p = accept_prob_logit(soc, decision_price, wait_h,
                                              args.beta0, args.beta1, args.beta2, args.beta3)

                    if args.strategy == "tou" and decision_price >= 0.40 and soc > 0.15:
                        acc_p = 0.0

                    if decision_price <= 0.20:   coef = 1.10   
                    elif decision_price >= 0.40: coef = 0.01   
                    else:                         coef = 0.45   
                    acc_p *= coef

                    if wait_h > 0.5:
                        acc_p = 0.0

                    acc_p = max(0.0, min(1.0, acc_p))
                    if random.random() < acc_p:
                        try:
                            traci.vehicle.setChargingStationStop(vid, cs, duration=-1)
                            assigned.add(vid)
                            last_accept[cs] = t
                            queue_len += 1
                        except: pass

        P = 0.0
        for cs, meta in stations.items():
            lane = meta["lane"]; s = meta["start"]; e = meta["end"]; pkw = meta["power_kw"]
            for vid in traci.lane.getLastStepVehicleIDs(lane):
                vpos = traci.vehicle.getLanePosition(vid)
                if s <= vpos <= e and traci.vehicle.getSpeed(vid) < 0.1:
                    util[cs] += 1
                    rev[cs]  += (pkw / 3600.0) * charge_price
                    P += pkw
                    break
        totalP.append(P)
        step += 1

    traci.close()

    total_steps = max(1, len(totalP))
    par = (max(totalP)/(mean(totalP)+1e-9)) if totalP else 0.0
    util_rate = {cs: util[cs]/total_steps for cs in stations}
    total_revenue = sum(rev.values())

    out_path = os.path.join(os.path.dirname(routes), args.out)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["strategy", args.strategy])
        if args.strategy == "tou":
            w.writerow(["tou_schedule", "peak 0.40 (7-10,17-20); off-peak 0.20 (22-6); else 0.30"])
            w.writerow(["start_h", args.start_h]); w.writerow(["start_min", args.start_min])
        if args.strategy in ("ppo_csv","ppo_time"):
            w.writerow(["base_$/kWh", args.base]); w.writerow(["spread_$/kWh", args.spread])
            w.writerow(["period_s", args.period])
        w.writerow(["cooldown_s", args.cooldown])
        w.writerow([])
        w.writerow(["station_id","utilization_rate","revenue_$"])
        for cs in stations:
            w.writerow([cs, round(util_rate[cs],4), round(rev[cs],2)])
        w.writerow([])
        w.writerow(["TOTAL_revenue_$", round(total_revenue,2)])
        w.writerow(["PAR_peak_to_avg_power", round(par,4)])
        w.writerow(["total_steps", total_steps])

    price_csv_path = os.path.join(os.path.dirname(routes), "controlled_prices.csv")
    with open(price_csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "decision_price_$per_kWh", "charge_price_$per_kWh"])
        for t, dp, cp in price_series:
            w.writerow([int(t), round(dp, 4), round(cp, 4)])
    print("Wrote price timeseries to", price_csv_path)

    print("Done:", args.strategy, "| Revenue:", round(total_revenue,2), "| PAR:", round(par,2))

if __name__ == "__main__":
    main()