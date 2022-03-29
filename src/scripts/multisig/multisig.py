import json
import os
from typing import Any, Optional

from algosdk import mnemonic
from algosdk.algod import AlgodClient
from algosdk.future.transaction import *

def send_multisig_tx(app_id:int, fn_name:str, app_args:Optional[List[Any]], foreign_apps:Optional[List[int]]):
    # Change these values with mnemonics
    mnemonic1 = os.getenv("MNEMONIC1")
    mnemonic2 = os.getenv("MNEMONIC2")
    mnemonic3 = os.getenv("MNEMONIC3")
    # mnemonic4 = os.getenv("MNEMONIC4")
    # never use mnemonics in production code, replace for demo purposes only

    # For ease of reference, add account public and private keys to
    # an accounts dict.

    private_key_1 = mnemonic.to_private_key(mnemonic1)
    account_1 = mnemonic.to_public_key(mnemonic1)

    private_key_2 = mnemonic.to_private_key(mnemonic2)
    account_2 = mnemonic.to_public_key(mnemonic2)

    private_key_3 = mnemonic.to_private_key(mnemonic3)
    account_3 = mnemonic.to_public_key(mnemonic3)

    # create a multisig account
    version = 1  # multisig version
    threshold = 3  # how many signatures are necessary
    msig = Multisig(version, threshold, [account_1, account_2, account_3])

    print("Multisig Address: ", msig.address())
    print(
        "Go to the below link to fund the created account using testnet faucet: \
        \n https://dispenser.testnet.aws.algodev.network/?account={}".format(
            msig.address()
        )
    )

    input("Press Enter to continue...")

    # sandbox
    algod_address = "http://localhost:4001"
    algod_token = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    # Initialize an algod client
    algod_client = AlgodClient(algod_token, algod_address)

    # get suggested parameters
    params = algod_client.suggested_params()
    # comment out the next two (2) lines to use suggested fees
    # params.flat_fee = True
    # params.fee = 1000

    # create a transaction
    sender = msig.address()
    note = "Team Multisig".encode()
    txn = ApplicationNoOpTxn(sender, params, app_id, note=note, app_args=[fn_name]+app_args, foreign_apps=foreign_apps)

    # create a SignedTransaction object
    mtx = MultisigTransaction(txn, msig)

    # sign the transaction
    mtx.sign(private_key_1)
    mtx.sign(private_key_2)
    mtx.sign(private_key_3)
    # print encoded transaction
    # print(encoding.msgpack_encode(mtx))


    # wait for confirmation
    try:
        # send the transaction
        txid = algod_client.send_raw_transaction(encoding.msgpack_encode(mtx))
        print("TXID: ", txid)
        confirmed_txn = wait_for_confirmation(algod_client, txid, 6)
        print("Result confirmed in round: {}".format(confirmed_txn["confirmed-round"]))
        print("Transaction information: {}".format(json.dumps(confirmed_txn, indent=4)))
        print("Decoded note: {}".format(base64.b64decode(confirmed_txn["txn"]["txn"]["note"]).decode()))
    except Exception as err:
        print(err)
