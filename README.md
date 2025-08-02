# CONVO CART 

### End-User Capabilities (via WhatsApp)

An end-user (customer) interacting with the bot on WhatsApp can:
* **Initiate an Order**: Start an ordering session by clicking a unique `wa.me` link specific to a business group[cite: 94, 454, 1262].
* **Place Orders**: Submit order details in a free-form text message after being prompted[cite: 446, 470, 513].
* **Receive Confirmations**: Get automated messages confirming their order has been saved and is pending review[cite: 378, 516].
* **Select Payment Options**: Choose between paying with **M-Pesa** or **Cash on Delivery** via interactive buttons[cite: 384, 439, 472].
* **Submit Payment Details**: Send an M-Pesa transaction code or message, which the system saves as a payment reference[cite: 448, 508].
* **Get Status Updates**: Receive automated notifications when an admin updates their order or payment status[cite: 391, 546, 559].
* **Track Orders**: Request a summary of their three most recent orders, including status, payment details, and the store name[cite: 443, 492].

***

### Administrative Capabilities (via Web Panel)

The system provides a secure, role-based web panel for managing the bot and its operations.

#### **Client Admin Role**

A **Client Admin** is a standard user who can manage the groups they are assigned to. Their capabilities include:
* **Dashboard View**: See an overview of key statistics like total, pending, and completed orders, but only for the groups they manage[cite: 527, 530, 1139].
* **Order Management**: View, filter, and manage orders associated with their assigned groups[cite: 534, 1187]. They can update an order's status (e.g., from `pending` to `processing`), modify the total amount, update payment details, and trigger a WhatsApp notification to the customer[cite: 541, 1211, 1219].
* **Group Management**: Create and edit the details of the groups they are assigned to, including the group name and welcome message[cite: 569, 582].

#### **Super Admin Role**

A **Super Admin** has complete control over the entire system, with all the capabilities of a Client Admin plus the following:
* **Full Data Access**: View and manage all orders, customers, and groups across the entire system without restriction[cite: 527, 568, 1154].
* **User Management**: Full authority to create, edit, and delete all users[cite: 631, 719]. They can assign user roles (`client_admin` or `super_admin`) and associate client admins with specific groups[cite: 637, 641, 676].
* **System Settings Configuration**: Modify critical system-wide settings, such as the WhatsApp API URL, Phone ID, API Token, and Webhook Verification Token[cite: 591, 1054, 1062].
* **Link Generation**: Access a tool to generate `wa.me` click-to-chat links for any active group in the system[cite: 618, 1108].
* **System Maintenance**: Reload the WhatsApp service configuration and send test messages directly from the settings panel to validate the API connection without restarting the application[cite: 608, 613, 1071].