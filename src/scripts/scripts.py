import time
from typing import Optional, Union
from typing import Tuple

from algosdk.future import transaction
from algosdk.logic import get_application_address
from algosdk.v2client.algod import AlgodClient
from algosdk.future.transaction import Multisig

from src.contracts.contracts import approval_program
from src.contracts.contracts import clear_state_program
from src.utils.account import Account
from src.utils.senders import send_no_op_tx
from src.utils.util import fullyCompileContract
from src.utils.util import getAppGlobalState
from src.utils.util import waitForTransaction
from algosdk.future.transaction import create_dryrun


APPROVAL_PROGRAM = b""
CLEAR_STATE_PROGRAM = b""


class Scripts:
    """
    A collection of helper scripts for quickly calling contract methods
    used only for testing and deploying

    note:
    these scripts are only examples.
    they haven't been audited.
    other scripts will do just fine to call the contract methods.

    """

    def __init__(
        self,
        client: AlgodClient,
        tipper: Account,
        reporter: Account,
        governance_address: Union[Account, Multisig],
        feed_app_id: Optional[int] = None,
        medianizer_app_id: Optional[int] = None,
    ) -> None:
        """
        - connects to algorand node
        - initializes some dummy accounts used for contract testing

        Args:
            client (AlgodClient): the algorand node we connect to read state and send transactions
            tipper (src.utils.account.Account): an account that deploys the contract and requests data
            reporter (src.utils.account.Account): an account that stakes ALGO tokens and submits data
            governance_address (src.utils.account.Account): an account that decides the quality of the reporter's data

        """

        self.client = client
        self.tipper = tipper
        self.reporter = reporter
        self.governance_address = governance_address
        self.feed_app_id = feed_app_id
        self.medianizer_app_id = medianizer_app_id

        self.feeds = []

        if self.feed_app_id is not None:
            self.feed_app_address = get_application_address(self.feed_app_id)
        if self.medianizer_app_id is not None:
            self.medianizer_app_address = get_application_address(self.medianizer_app_id)

    def get_contracts(self, client: AlgodClient) -> Tuple[bytes, bytes]:
        """
        Get the compiled TEAL contracts for the tellor contract.

        Args:
            client: An algod client that has the ability to compile TEAL programs.
        Returns:
            A tuple of 2 byte strings. The first is the approval program, and the
            second is the clear state program.
        """
        global APPROVAL_PROGRAM
        global CLEAR_STATE_PROGRAM

        if len(APPROVAL_PROGRAM) == 0:
            APPROVAL_PROGRAM = fullyCompileContract(client, approval_program())
            CLEAR_STATE_PROGRAM = fullyCompileContract(client, clear_state_program())

        return APPROVAL_PROGRAM, CLEAR_STATE_PROGRAM

    def get_medianized_value(self):

        state = getAppGlobalState(self.client, self.medianizer_app_id)

        return state["median"]

    def get_current_feeds(self):

        state = getAppGlobalState(self.client, self.medianizer_app_id)

        current_data = {}

        for i in range(5):
            feed_app_id = state["app_" + i]
            feed_state = getAppGlobalState(self.client, feed_app_id)
            current_data[feed_app_id]["values"] = feed_state["values"]
            current_data[feed_app_id]["timestamps"] = feed_state["timestamps"]

    def deploy_tellor_flex(self, query_id: str, query_data: str) -> int:
        """
        Deploy a new tellor reporting contract.
        calls create() method on contract

        Args:
            client: An algod client.
            sender: The account that will request data through the contract
            governance_address: the account that can vote to dispute reports
            query_id: the ID of the data requested to be put on chain
            query_data: the in-depth specifications of the data requested
        Returns:
            int: The ID of the newly created auction app.
        """
        approval, clear = self.get_contracts(self.client)

        globalSchema = transaction.StateSchema(num_uints=7, num_byte_slices=6)
        localSchema = transaction.StateSchema(num_uints=0, num_byte_slices=0)

        app_args = [
            self.governance_address.getAddress(),
            query_id.encode("utf-8"),
            query_data.encode("utf-8"),
        ]

        txn = transaction.ApplicationCreateTxn(
            sender=self.tipper.getAddress(),
            on_complete=transaction.OnComplete.NoOpOC,
            approval_program=approval,
            clear_program=clear,
            global_schema=globalSchema,
            local_schema=localSchema,
            app_args=app_args,
            sp=self.client.suggested_params(),
        )

        signedTxn = txn.sign(self.tipper.getPrivateKey())

        self.client.send_transaction(signedTxn)

        response = waitForTransaction(self.client, signedTxn.get_txid())
        assert response.applicationIndex is not None and response.applicationIndex > 0
        self.feed_app_id = response.applicationIndex
        self.app_address = get_application_address(self.feed_app_id)
        return self.feed_app_id

    def stake(self, stake_amount=None) -> None:
        """
        Send 2-txn group transaction to...
        - send the stake amount from the reporter to the contract
        - call stake() on the contract

        Args:
            stake_amount (int): override stake_amount for testing purposes
        """
        appGlobalState = getAppGlobalState(self.client, self.feed_app_id)

        if stake_amount is None:
            stake_amount = appGlobalState[b"stake_amount"]

        suggestedParams = self.client.suggested_params()

        payTxn = transaction.PaymentTxn(
            sender=self.reporter.getAddress(),
            receiver=self.app_address,
            amt=stake_amount,
            sp=suggestedParams,
        )

        stakeInTx = transaction.ApplicationNoOpTxn(
            sender=self.reporter.getAddress(),
            index=self.feed_app_id,
            app_args=[b"stake"],
            sp=self.client.suggested_params(),
        )

        transaction.assign_group_id([payTxn, stakeInTx])

        signedPayTxn = payTxn.sign(self.reporter.getPrivateKey())
        signedAppCallTxn = stakeInTx.sign(self.reporter.getPrivateKey())

        self.client.send_transactions([signedPayTxn, signedAppCallTxn])

        waitForTransaction(self.client, stakeInTx.get_txid())

    def tip(self, tip_amount: int) -> None:

        suggestedParams = self.client.suggested_params()

        payTxn = transaction.PaymentTxn(
            sender=self.tipper.getAddress(), receiver=self.app_address, amt=tip_amount, sp=suggestedParams
        )

        no_op_txn = transaction.ApplicationNoOpTxn(
            sender=self.tipper.getAddress(), index=self.feed_app_id, app_args=[b"tip"], sp=suggestedParams
        )

        signed_pay_txn = payTxn.sign(self.tipper.getPrivateKey())
        signed_no_op_txn = no_op_txn.sign(self.tipper.getPrivateKey())

        self.client.send_transactions([signed_pay_txn, signed_no_op_txn])

        waitForTransaction(self.cient, no_op_txn.get_txid())

    def report(self, query_id: bytes, value: bytes):
        """
        Call report() on the contract to set the current value on the contract

        Args:
            - query_id (bytes): the unique identifier representing the type of data requested
            - value (bytes): the data the reporter submits on chain
        """

        submitValueTxn = transaction.ApplicationNoOpTxn(
            sender=self.reporter.getAddress(),
            index=self.feed_app_id,
            app_args=[b"report", query_id, value],
            sp=self.client.suggested_params(),
        )

        signedSubmitValueTxn = submitValueTxn.sign(self.reporter.getPrivateKey())
        self.client.send_transaction(signedSubmitValueTxn)
        waitForTransaction(self.client, signedSubmitValueTxn.get_txid())

    def withdraw(self, ff_time:int=0):
        """
        Sends the reporter their stake back and removes their permission to report
        calls withdraw() on the contract
        """

        if ff_time == 0:
            txn = transaction.ApplicationNoOpTxn(
                sender=self.reporter.getAddress(),
                index=self.feed_app_id,
                app_args=[b"withdraw"],
                sp=self.client.suggested_params(),
            )
            signedTxn = txn.sign(self.reporter.getPrivateKey())
            self.client.send_transaction(signedTxn)
            waitForTransaction(self.client, signedTxn.get_txid())
        else:
            txn = transaction.ApplicationNoOpTxn(
                sender=self.reporter.getAddress(),
                index=self.feed_app_id,
                app_args=[b"withdraw"],
                sp=self.client.suggested_params(),
            )
            signedTxn = txn.sign(self.reporter.getPrivateKey())
            dr_request = create_dryrun(self.client, [txn], latest_timestamp= time.time() + ff_time)
            dr_response = self.client.dryrun(dr_request)
            dr_result = dr_request.DryrunResponse(dr_response)
            for txn in dr_result.txns:
                    if txn.app_call_rejected():
                        print(txn.app_trace(dryrun_results.StackPrinterConfig(max_value_width=0)))

    def request_withdraw(self):

        send_no_op_tx(self.reporter, self.feed_app_id, "request_withdraw", app_args=None, foreign_apps=None)
