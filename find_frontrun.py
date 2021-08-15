import base64
import json

from requests import Session

apikey = ""

url_head = "https://terra--search.datahub.figment.io/apikey/"
url_tail = "/transactions_search"
url = url_head + apikey + url_tail

block_cache = {}
headers = {"content-type": "application/json"}
oracle_feeder = "terra1zue382qey9l5uhhwcwumjhmsne49a0agwhd60d"

first_block = 3757709
last_block = 3816781


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


def print_frontruns(liquidation_attempts: list) -> None:
    for liquidation in liquidation_attempts:
        if liquidation["frontrun"]:
            print(liquidation["hash"])


def check_next_block_frontrun(height, liquidator, s):
    block = get_block(height + 1, s)

    if block is None:
        return False

    for tx in block:
        if check_tx_type(tx, "execute_contract"):
            if check_sender(tx, liquidator):  # if liquidator then check the next next tx
                continue
            elif check_sender(tx, oracle_feeder):  # if price_feed then return true
                return True
            else:  # otherwise return false
                return False
        else:  # if tx isn't a execute_contract, then it can't be a liq tx or price_feed tx, return false
            return False

    return False  # if next block is finished without finding the price_feed or returning false, assume the tx wasn't frontrun


def check_frontrun(liquidation_list, liquidator, s):
    """
    This method checks if the liq tx from the liquidator frontruns the price_feed tx from
    the oracle feeder by getting the block, finding the liquidation tx, and checking the
    tx after to it. If the liq tx is index 0 of the block, we check the prior block for the
    price_feed tx.

    Given [some_tx, liq_tx 1, ... liq_tx n, price_feed], all liq_tx are considered frontrun
    Given [some_tx, price_feed, liq_tx 1, ... liq_tx n], all liq_txs are considered not frontrun

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
                            if i < len(block) - 1:
                                if check_tx_type(block[i + 1], "execute_contract"):
                                    if check_sender(block[i + 1], oracle_feeder):  # if next tx is from oracle feeder
                                        liquidation["frontrun"] = True
                                        break
                            else:
                                liquidation["frontrun"] = check_next_block_frontrun(liq_height, liquidator, s)

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
                            "frontrun": False,
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
        liquidation_list = get_liq_txs(liquidator, first_block, last_block, s)
        liquidation_list = check_frontrun(liquidation_list, liquidator, s)

    return liquidation_list


def main():
    """ """
    liquidator = "terra18kgwjqrm7mcnlzcy7l8h7awnn7fs2pvdl2tpm9"
    liquidation_list = create_liquidation_list(liquidator)
    print_frontruns(liquidation_list)


if __name__ == "__main__":
    if apikey == "":
        print("figment.io apikey missing")
        quit()

    main()
