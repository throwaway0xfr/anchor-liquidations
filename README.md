# anchor-liquidations

Requires a free figment.io terra api key.

https://auth.figment.io/sign_up

Add the api key to line 8 of liquidator_stats.py
```
apikey = "yourapikey"
```

Install
```
python3 -m venv env
source env/bin/activate
pip3 install -r requirements.txt
```

Run
```
python3 liquidator_stats.py
python3 find_frontrun.py
```
The script uses figment.io's transaction search api to get all liquidation attempts by liquidators in the liquidator_list and compiles stats on backrunning and frontrunning. It also plots that data into matplotlib and saves the graph to disk.

The script downloads and cache's about 6GB of blocks into memory. Takes about 12 mins on a 1gbps line and requires 6GB of memory.

If you are ram constrained, comment out the following lines and ram usage will go from 6GB to 170MB, but runtime will increase by 3-4x

Line 46 on liquidator_stats.py
```
block_cache[height] = block
```
Line 43 on find_frontrun.py
```
block_cache[height] = block
```
