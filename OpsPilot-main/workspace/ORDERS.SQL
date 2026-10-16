CREATE OR REPLACE PACKAGE BODY order_processor AS

    PROCEDURE process_pending_orders (
        p_customer_id IN NUMBER,
        p_status_out  OUT VARCHAR2
    ) IS
        v_order_id   NUMBER;
        v_total_amt  NUMBER := 0;
        v_discount   NUMBER := 0;
        v_item_price NUMBER;

        CURSOR c_orders IS
            SELECT order_id, order_date, total_amount
            FROM orders
            WHERE customer_id = p_customer_id
              AND status = 'PENDING'
            FOR UPDATE OF status;

        CURSOR c_order_items (p_ord_id NUMBER) IS
            SELECT item_id, quantity, unit_price
            FROM order_items
            WHERE order_id = p_ord_id;

    BEGIN
        p_status_out := 'SUCCESS';

        FOR r_order IN c_orders LOOP
            v_order_id := r_order.order_id;
            v_total_amt := 0;

            FOR r_item IN c_order_items(v_order_id) LOOP
                v_item_price := r_item.quantity * r_item.unit_price;
                v_total_amt := v_total_amt + v_item_price;

                UPDATE inventory
                SET stock_qty = stock_qty - r_item.quantity
                WHERE item_id = r_item.item_id;
            END LOOP;

            IF v_total_amt > 1000 THEN
                v_discount := v_total_amt * 0.10;
            ELSE
                v_discount := 0;
            END IF;

            UPDATE orders
            SET total_amount = v_total_amt - v_discount,
                status = 'PROCESSED',
                updated_at = SYSDATE
            WHERE order_id = v_order_id;

            INSERT INTO audit_log (log_id, action, entity_id, timestamp)
            VALUES (audit_seq.NEXTVAL, 'ORDER_PROCESSED', v_order_id, SYSDATE);

        END LOOP;

        COMMIT;

    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            p_status_out := 'ERR_NO_DATA';
            ROLLBACK;
        WHEN OTHERS THEN
            p_status_out := 'ERR_INTERNAL: ' || SQLERRM;
            ROLLBACK;
    END process_pending_orders;

END order_processor;
/
