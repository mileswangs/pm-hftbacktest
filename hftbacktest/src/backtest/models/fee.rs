use crate::{prelude::Side, types::Order};

/// Common transaction fees
/// Fee calculation is determined by the fee model.
#[derive(Clone)]
pub struct CommonFees {
    /// Fee for adding liquidity (maker order).
    maker_fee: f64,
    /// Fee for removing liquidity (taker order).
    taker_fee: f64,
}

impl CommonFees {
    /// Constructs `CommonFees`.
    pub fn new(maker_fee: f64, taker_fee: f64) -> Self {
        Self {
            maker_fee,
            taker_fee,
        }
    }

    #[inline]
    fn select(&self, maker: bool) -> f64 {
        if maker {
            self.maker_fee
        } else {
            self.taker_fee
        }
    }
}

/// Directional fees, such as stamp duty, are typically charged based on the transaction value in
/// addition to the common transaction fees.
#[derive(Clone)]
pub struct DirectionalFees {
    /// The common transaction fees
    common_fees: CommonFees,
    /// Buyer fee based on the transaction value
    buyer_fee: f64,
    /// Seller fee based on the transaction value
    seller_fee: f64,
}

impl DirectionalFees {
    /// Constructs `DirectionalFees`.
    pub fn new(common_fees: CommonFees, buyer_fee: f64, seller_fee: f64) -> Self {
        Self {
            common_fees,
            buyer_fee,
            seller_fee,
        }
    }
}

/// Provides the fee.
pub trait FeeModel {
    /// Calculates the fee amount.
    fn amount(&self, order: &Order, amount: f64) -> f64;
}

/// Fee based on the transaction value,
/// with the rate depending on whether the order is a maker or taker.
#[derive(Clone)]
pub struct TradingValueFeeModel<Fees> {
    fees: Fees,
}

impl<Fees> TradingValueFeeModel<Fees> {
    /// Constructs `TradingValueFeeModel`.
    pub fn new(fees: Fees) -> Self {
        Self { fees }
    }
}

impl FeeModel for TradingValueFeeModel<CommonFees> {
    fn amount(&self, order: &Order, amount: f64) -> f64 {
        self.fees.select(order.maker) * amount
    }
}

impl FeeModel for TradingValueFeeModel<DirectionalFees> {
    fn amount(&self, order: &Order, amount: f64) -> f64 {
        match (order.maker, order.side) {
            (true, Side::Buy) => (self.fees.common_fees.maker_fee + self.fees.buyer_fee) * amount,
            (false, Side::Buy) => (self.fees.common_fees.taker_fee + self.fees.buyer_fee) * amount,
            (true, Side::Sell) => (self.fees.common_fees.maker_fee + self.fees.seller_fee) * amount,
            (false, Side::Sell) => {
                (self.fees.common_fees.taker_fee + self.fees.seller_fee) * amount
            }
            _ => unreachable!(),
        }
    }
}

/// Fee based on the transaction quantity,
/// with the rate depending on whether the order is a maker or taker.
#[derive(Clone)]
pub struct TradingQtyFeeModel<Fees> {
    fees: Fees,
}

impl<Fees> TradingQtyFeeModel<Fees> {
    /// Constructs `TradingQtyFeeModel`.
    pub fn new(fees: Fees) -> Self {
        Self { fees }
    }
}
impl FeeModel for TradingQtyFeeModel<CommonFees> {
    fn amount(&self, order: &Order, _amount: f64) -> f64 {
        self.fees.select(order.maker) * order.exec_qty
    }
}

impl FeeModel for TradingQtyFeeModel<DirectionalFees> {
    fn amount(&self, order: &Order, amount: f64) -> f64 {
        match (order.maker, order.side) {
            (true, Side::Buy) => {
                self.fees.common_fees.maker_fee * order.exec_qty + self.fees.buyer_fee * amount
            }
            (false, Side::Buy) => {
                self.fees.common_fees.taker_fee * order.exec_qty + self.fees.buyer_fee * amount
            }
            (true, Side::Sell) => {
                self.fees.common_fees.maker_fee * order.exec_qty + self.fees.seller_fee * amount
            }
            (false, Side::Sell) => {
                self.fees.common_fees.taker_fee * order.exec_qty + self.fees.seller_fee * amount
            }
            _ => unreachable!(),
        }
    }
}

/// Fee for binary outcome contracts, based on the execution quantity and price.
///
/// The amount is `quantity * fee_rate * price * (1 - price)`, with the rate depending on whether
/// the order is a maker or taker.
#[derive(Clone)]
pub struct BinaryFeeModel<Fees> {
    fees: Fees,
}

impl<Fees> BinaryFeeModel<Fees> {
    /// Constructs `BinaryFeeModel`.
    pub fn new(fees: Fees) -> Self {
        Self { fees }
    }
}

impl FeeModel for BinaryFeeModel<CommonFees> {
    fn amount(&self, order: &Order, _amount: f64) -> f64 {
        let price = order.exec_price();
        self.fees.select(order.maker) * order.exec_qty * price * (1.0 - price)
    }
}

/// Flat fee per trade
#[derive(Clone)]
pub struct FlatPerTradeFeeModel<Fees> {
    fees: Fees,
}
impl<Fees> FlatPerTradeFeeModel<Fees> {
    /// Constructs `FlatPerTradeFeeModel`.
    pub fn new(fees: Fees) -> Self {
        Self { fees }
    }
}

impl FeeModel for FlatPerTradeFeeModel<CommonFees> {
    fn amount(&self, order: &Order, _amount: f64) -> f64 {
        self.fees.select(order.maker)
    }
}

#[cfg(test)]
mod tests {
    use super::{BinaryFeeModel, CommonFees, FeeModel};
    use crate::prelude::{OrdType, Order, Side, TimeInForce};

    fn executed_order(price: f64, qty: f64, maker: bool) -> Order {
        let tick_size = 0.001;
        let mut order = Order::new(
            1,
            900,
            tick_size,
            qty * 2.0,
            Side::Buy,
            OrdType::Limit,
            TimeInForce::GTC,
        );
        order.exec_price_tick = (price / tick_size).round() as i64;
        order.exec_qty = qty;
        order.maker = maker;
        order
    }

    fn assert_close(actual: f64, expected: f64) {
        assert!(
            (actual - expected).abs() < 1e-12,
            "expected {expected}, got {actual}"
        );
    }

    #[test]
    fn binary_fee_uses_execution_quantity_and_price() {
        let model = BinaryFeeModel::new(CommonFees::new(0.01, 0.02));
        let order = executed_order(0.4, 100.0, false);

        assert_close(model.amount(&order, 999_999.0), 0.48);
    }

    #[test]
    fn binary_fee_selects_maker_or_taker_rate() {
        let model = BinaryFeeModel::new(CommonFees::new(-0.01, 0.02));
        let maker_order = executed_order(0.5, 100.0, true);
        let taker_order = executed_order(0.5, 100.0, false);

        assert_close(model.amount(&maker_order, 0.0), -0.25);
        assert_close(model.amount(&taker_order, 0.0), 0.5);
    }

    #[test]
    fn binary_fee_is_symmetric_around_half() {
        let model = BinaryFeeModel::new(CommonFees::new(0.0, 0.02));
        let low_price_order = executed_order(0.2, 100.0, false);
        let high_price_order = executed_order(0.8, 100.0, false);

        assert_close(
            model.amount(&low_price_order, 0.0),
            model.amount(&high_price_order, 0.0),
        );
    }

    #[test]
    fn binary_fee_is_zero_at_binary_price_boundaries() {
        let model = BinaryFeeModel::new(CommonFees::new(0.01, 0.02));
        let zero_price_order = executed_order(0.0, 100.0, false);
        let one_price_order = executed_order(1.0, 100.0, false);

        assert_close(model.amount(&zero_price_order, 0.0), 0.0);
        assert_close(model.amount(&one_price_order, 0.0), 0.0);
    }
}
