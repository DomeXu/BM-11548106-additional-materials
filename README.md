# BM-11548106-additional-materials

This repository contains the supplementary materials for the MSc dissertation project.  
It includes datasets references, preprocessing scripts, PPO training notebooks, and SUMO simulation code to ensure reproducibility.

---

## 1. Data Sources

This project relies on two publicly available datasets:

1. **CAISO Market Data**  
   - Source: [OASIS CAISO](https://oasis.caiso.com/mrioasis/logon.do)  
   - Example file: `20240701_20240722_PRC_LMP_DAM_20250719_15_20_37_v12.csv`  
   - Role: Provides day-ahead wholesale electricity prices in California, used to evaluate charging cost dynamics.  

2. **NREL EV Charging Dataset**  
   - Source: [NREL Open Data](https://data.openei.org/submissions/8237)  
   - Example file: `dataSet_Oct2021.csv`  
   - Role: Contains electric vehicle user charging behaviors, used to train the PPO policy.  

⚠️ Note: Due to size and licensing, raw datasets are **not included** in this repository. Please download them from the official sources.

---

## 2. Code and Scripts

### 2.1 Main Workflow (Jupyter Notebooks)
- `Code.ipynb` – Implements the full workflow: data preprocessing, feature extraction, PPO training, and export of the learned charging strategy.  
- `ppo_csv_normalised.csv` – Processed dataset used as input to PPO-based SUMO experiments.  

### 2.2 Data Cleaning
- `Cleaned_ev_users_with_pricing_action.py`  
  - **Input**: `ev_users_with_pricing_action.csv`  
  - **Output**: `ppo_csv_normalised.csv`  
  - **Function**: Cleans and normalises EV user data for PPO training.  

### 2.3 SUMO Simulation
1. `gen_scenario.py`  
   - Builds the SUMO environment:  
     - Road network: `ev_map.net.xml`  
     - Trip file: `trips_600.trips`  
     - EV routes: `ev_routes_ev_600.rou.xml`  
     - Charging station configuration: `additional_stop.add.xml`  

2. `run_kpi_perfect2x2.py`  
   - Runs SUMO simulations under different charging strategies:  
     - **Flat** – Fixed price  
     - **ToU** – Time-of-use pricing  
     - **PPO-CSV** – Policy based on PPO training results  
     - **PPO-Time** – PPO with time-window strategy  
   - Key arguments: `--strategy`, `--csv`, `--start-h`, `--soc-thres`, etc.  

   **Example (PPO-CSV run):**
   ```bash
   python run_kpi_perfect2x2.py --gui --strategy ppo_csv \
       --routes ev_routes_ev_600.rou.xml \
       --additional additional_stop.add.xml \
       --csv ppo_csv_normalised.csv \
       --base 0.28 --spread 0.18 \
       --start-h 21 --start-min 30 \
       --soc-thres 0.60 --target-soc 0.90 \
       --beta0 -1.0 --beta1 2.8 --beta2 -2.5 --beta3 -1.8 \
       --cooldown 30 --out ppo_csv_valley.csv


