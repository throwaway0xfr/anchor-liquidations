import base64
import json

import matplotlib.pyplot as plt
import numpy as np
from requests import Session

apikey = ""

url_head = "https://terra--search.datahub.figment.io/apikey/"
url_tail = "/transactions_search"
url = url_head + apikey + url_tail

block_cache = {}
headers = {"content-type": "application/json"}
oracle_feeder = "terra1zue382qey9l5uhhwcwumjhmsne49a0agwhd60d"

first_liq_block = 2287317
last_liq_block = 3816781
suspect_activity_block = 3757709


def get_block(height: int, s: Session) -> list:
    """
    Gets the specified block from figment tx search
    :param height: int of block
    :param s: session
    :return: list containing block
    """
    if height in block_cache:  # return block if already cached
        return block_cache[height]

    data = {"network": "terra", "height": height}

    res = s.post(url, data=json.dumps(data), headers=headers)
    block = res.json()

    if block:
        if len(block) == 100:
            data = {"network": "terra", "height": height, "offset": 100}
            res = s.post(url, data=json.dumps(data), headers=headers)
            if res.json():
                for tx in res.json():
                    block.append(tx)

    block_cache[height] = block  # cache block to reduce api requests
    return block


def get_msg_list(tx: dict) -> list:
    """
    Takes a tx dict, decodes and returns the msg list
    :param tx: tx dict
    :return: decoded msg list
    """
    decoded_msg_list = []
    msg_list = tx["events"][0]["sub"][0]["additional"]["execute_message"]
    for msg in msg_list:
        decoded_msg = json.loads(base64.b64decode(msg))
        decoded_msg_list.append(decoded_msg)

    return decoded_msg_list


def get_txs(sender: str, after_height: int, before_height: int, offset: int, s: Session) -> list:
    """
    Uses figment.io transaction search to get thne next 100 txs from sender based on offset
    :param sender: str containing sender's address
    :param after_height: gets txs after this height
    :param before_height: gets txs before this height
    :param offset: offset used because of figment's 100 tx limit
    :param s: session
    :return:
    """
    limit = 100
    data = {
        "network": "terra",
        "before_height": before_height,
        "after_height": after_height,
        "sender": [sender],
        "offset": offset,
        "limit": limit,
    }
    res = s.post(url, data=json.dumps(data), headers=headers)
    return res.json()


def check_tx_type(tx: dict, kind: str) -> bool:
    """
    :param tx: transaction dictionary
    :param kind: string containing tx type
    :return: boolean
    """
    if tx["events"][0]["kind"] == kind:
        return True

    return False


def check_sender(tx: dict, sender: str) -> bool:
    """
    :param tx: transaction dictionary
    :param sender: string containing sender's address
    :return: boolean
    """
    if tx["events"][0]["sub"][0]["sender"][0]["account"]["id"] == sender:
        return True

    return False


def get_sender(tx: dict) -> str:
    """
    Returns the tx sender's address
    :param tx: transaction dictionary
    :return: str
    """
    return tx["events"][0]["sub"][0]["sender"][0]["account"]["id"]


def liquidator_stats(liquidation_attempts: list, liquidator: str) -> None:
    """
    Takes a liquidation list and finds the number of txs that are backrun,
    stats are seperated before and after suspect block activity
    :param liquidation_attempts: list
    :param liquidator: str
    """
    before_total = 0
    before_backrun = 0
    after_total = 0
    after_backrun = 0

    for liquidation in liquidation_attempts:
        if liquidation["height"] < suspect_activity_block:
            before_total += 1
            if liquidation["backrun"]:
                before_backrun += 1
        else:
            after_total += 1
            if liquidation["backrun"]:
                after_backrun += 1

    print("")
    print(liquidator)
    print(str(first_liq_block) + " to " + str(suspect_activity_block) + ":")
    print("Total: " + str(before_total))
    print("Backrun: " + str(before_backrun))
    if before_total > 0:
        print("Percent backrun: " + str(before_backrun / before_total * 100) + "%")
    else:
        print("Percent backrun: 0%")
    print("")

    print(str(suspect_activity_block) + " to " + str(last_liq_block) + ":")
    print("Total: " + str(after_total))
    print("Backrun: " + str(after_backrun))
    if after_total > 0:
        print("Percent backrun: " + str(after_backrun / after_total * 100) + "%")
    else:
        print("Percent backrun: 0%")


def generate_graph_data(liquidation_list: list) -> dict:
    """
    Generates graph data from liquidation list, txs every
    14400 blocks (~ one day) are grouped togather
    :param liquidation_list: list
    :return: dictionary containing graph data
    """
    graph_dict = {}
    interval = 14400
    block = first_liq_block

    for i in range(first_liq_block, last_liq_block, interval):
        graph_dict[i] = {"backrun": 0, "normal": 0}

    for liquidation in reversed(liquidation_list):
        height = liquidation["height"]

        if height > block + interval:
            block = block + interval

        if liquidation["backrun"]:
            graph_dict[block]["backrun"] += 1
        else:
            graph_dict[block]["normal"] += 1

    return graph_dict


def plot_graph(graph_dict: dict, liquidator: str) -> None:
    """
    Generates graph from graph_dict and saves to disk
    :param graph_dict: dictionary containing graph data
    :param liquidator: string
    """
    labels, backrun, normal = [], [], []

    for key, val in graph_dict.items():
        labels.append(key)
        backrun.append(val["backrun"])
        normal.append(val["normal"])

    x_axis = np.arange(len(labels))

    plt.figure()
    plt.title(liquidator)
    plt.xlabel("Height")
    plt.ylabel("Liquidation Attempts")

    plt.bar(x_axis - 0.2, backrun, 0.4, label="backrun")
    plt.bar(x_axis + 0.2, normal, 0.4, label="normal")
    plt.xticks(x_axis[::10], labels[::10], rotation=90)

    plt.legend()
    plt.tight_layout()
    plt.savefig(liquidator + ".png", format="png", dpi=600)
    plt.close()


def graph_txs(liquidation_list: list, liquidator: str) -> None:
    """
    Calls generate_graph and plot_graph
    :param liquidation_list: list
    :param liquidator: string
    """
    graph_dict = generate_graph_data(liquidation_list)
    plot_graph(graph_dict, liquidator)


def check_prev_block_backrun(height: int, liquidator: str, s: Session) -> bool:
    """
    This method is called if the liquidation tx is the first tx on the block,
    so we check the previous block in reverse order for the price_feed tx
    :param height: height of the next block
    :param liquidator: str containing liquidator's address
    :param s: session
    :return: returns true if price_feed tx found right before the liqiuidate tx,
             false in all other cases
    """
    block = get_block(height - 1, s)

    if block is None:
        return False

    for tx in reversed(block):  # reverse block
        if check_tx_type(tx, "execute_contract"):
            if check_sender(tx, liquidator):  # if liquidator then check the next reverse tx
                continue
            elif check_sender(tx, oracle_feeder):  # if price_feed then return true
                return True
            else:  # otherwise return false
                return False
        else:  # if tx isn't a execute_contract, then it can't be a liq tx or price_feed tx, return false
            return False

    return False  # if prev block is finished without finding the price_feed or returning false, assume the tx wasn't backrun


def check_backrun(liquidation_list: list, liquidator: str, s: Session) -> list:
    """
    This method checks if the liq tx from the liquidator backruns the price_feed tx from
    the oracle feeder by getting the block, finding the liquidation tx, and checking the
    tx prior to it. If the liq tx is index 0 of the block, we check the prior block for the
    price_feed tx.

    Given [some_tx, price_feed, liq_tx 1, ... liq_tx n], all liq_tx are considered backrun
    Given [some_tx, price_feed, some_tx, liq_tx 1, ... liq_tx n], all liq_txs are considered not backrun

    :param liquidation_list: list of liquidate_collateral from liquidator
    :param liquidator: str containing liquidator's address
    :param s: session
    :return: liquidation list with backrun information
    """
    for liquidation in liquidation_list:
        liq_height = liquidation["height"]

        block = get_block(liq_height, s)

        for i in range(len(block)):  # iterate the block
            if check_tx_type(block[i], "execute_contract"):
                if check_sender(block[i], liquidator):  # find the liquidator's tx
                    msg_list = get_msg_list(block[i])
                    for msg in msg_list:
                        if "liquidate_collateral" in msg:  # make sure its a liq tx
                            if i > 0:
                                if check_tx_type(block[i - 1], "execute_contract"):
                                    if check_sender(block[i - 1], oracle_feeder):  # if prior tx is from oracle feeder
                                        liquidation["backrun"] = True
                                        break
                            else:
                                liquidation["backrun"] = check_prev_block_backrun(liq_height, liquidator, s)

    return liquidation_list


def get_liq_txs(sender: str, after_height: int, before_height: int, s: Session) -> list:
    """
    This method gets all liquidate_collateral transations for a given address between after_height and
    before_height using figment.io transaction search
    :param sender: string of sender's address
    :param after_height: int
    :param before_height: int
    :param s: session
    :return: list of dicts containing liquidation txs
    """
    liq_list = []
    offset = 0

    while True:
        tx_list = get_txs(sender, after_height, before_height, offset, s)

        if not tx_list:
            break

        for tx in tx_list:  # iterate tx_list and find all liq txs from liquidator
            if check_tx_type(tx, "execute_contract"):
                msg_list = get_msg_list(tx)
                for msg in msg_list:
                    if "liquidate_collateral" in msg:
                        liq_tx = {  # save relevant data to dict
                            "hash": tx["hash"],
                            "height": tx["height"],
                            "execute_message": msg,
                            "sender": get_sender(tx),
                            "backrun": False,
                        }
                        liq_list.append(liq_tx)  # append dict to list
        offset += 100  # change offset to get next 100 txs

    return liq_list


def create_liquidation_list(liquidator: str) -> list:
    """
    This method calls get_liq_txs to generate the liquidation tx list from liquidator, then
    send the liquidation list to check_backrun
    :param liquidator: str contaiining the liquidator's address
    :param s: session
    :return: liquidation list that has been checked for backrunning
    """
    with Session() as s:
        liquidation_list = get_liq_txs(liquidator, first_liq_block, last_liq_block, s)
        liquidation_list = check_backrun(liquidation_list, liquidator, s)

    return liquidation_list


def main():
    """ """
    liquidators = [
        "terra18kgwjqrm7mcnlzcy7l8h7awnn7fs2pvdl2tpm9",
        "terra13wg8aj26kvzu2q0xwthkttwul4ud72t6y6z92r",
        "terra1dx8p5gkegpcamny5emt0z069cm6ekjuwxhqgdg",
        "terra1gcvztv0gmzqgyy0ae7v7v3rt0ggzktup9qzdnv",
        "terra14s9r9u67tjy5yk7v6m6056qsh2jg2lpzhmzvg5",
        "terra1v9l5hz9euqzm0hg4quh2gs32n9y99q9c4yhqqs",
        "terra1t58pt7mgj30cgm682zn3s4rykvxa9p7t0jl0xm",
        "terra1c0zj6xp7uzgctf2lqhthkdty828m29zyjdawd0",
        "terra1swt4gfylaq02tsek3gunevyuwp2egtukhwrs4q",
        "terra14l56n89zmf4km5m3xj7tq7p9f2w7zq6v2ly0xq",
    ]

    for liquidator in liquidators:
        liquidation_list = create_liquidation_list(liquidator)
        graph_txs(liquidation_list, liquidator)
        liquidator_stats(liquidation_list, liquidator)


if __name__ == "__main__":
    if apikey == "":
        print("figment.io apikey missing")
        quit()

    main()
