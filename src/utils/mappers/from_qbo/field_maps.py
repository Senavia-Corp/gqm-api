
# Map para Invoices y Bills (comparten los mismos campos)
QBO_FDOC_FIELD_MAP = {
    "Job_Ref_QBO": "DocNumber",
    "Total_Amount": "TotalAmt",
    "Balance_Amount": "Balance",
    "Notes": "PrivateNote",
    "Due_Date": "DueDate",
    "qbo_id": "Id"
}


# Map para Invoices Items
QBO_FDOCITEM_INVOICE_FIELD_MAP = {
    "Name": "SalesItemLineDetail.ItemRef.name",
    "Description": "Description",
    "Unit_price": "SalesItemLineDetail.UnitPrice",
    "Quantity": "SalesItemLineDetail.Qty",
    "Amount": "Amount",
    "qbo_line_id": "Id"
}


# Map para Bills Items
QBO_FDOCITEM_BILL_FIELD_MAP = {
    "Name": "ItemBasedExpenseLineDetail.ItemRef.name",
    "Description": "Description",
    "Unit_price": "ItemBasedExpenseLineDetail.UnitPrice",
    "Quantity": "ItemBasedExpenseLineDetail.Qty",
    "Amount": "Amount",
    "qbo_line_id": "Id"
}


# Map para Payments
QBO_FTRANS_INVOICE_FIELD_MAP = {
    "Reference_number": "PaymentRefNum",
    "Total_Amount": "TotalAmt",
    "Date_of_payment": "TxnDate",
    "qbo_id": "Id"
}


# Map para Bill Payments
QBO_FTRANS_BILL_FIELD_MAP = {
    "Reference_number": "DocNumber",
    "Total_Amount": "TotalAmt",
    "Bank_Account_Ref": "CheckPayment.BankAccountRef.name",
    "Type_of_payment": "PayType",
    "Date_of_payment": "TxnDate",
    "qbo_id": "Id"
}
