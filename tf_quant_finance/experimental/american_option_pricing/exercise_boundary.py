"""Calculating the exercise boundary function of an American option."""
from typing import Callable, Optional
import numpy as np
import tensorflow.compat.v2 as tf

from tf_quant_finance import types
from tf_quant_finance import utils
from tf_quant_finance.math.integration import gauss_legendre
from tf_quant_finance.math.interpolation.cubic import cubic_interpolation


build_spline = cubic_interpolation.build
interpolate = cubic_interpolation.interpolate
_SQRT_2 = np.sqrt(2.0, dtype=np.float64)


def _standard_normal_cdf(x):
  return (tf.math.erf(x / _SQRT_2) + 1) / 2


def _d_plus(tau: types.FloatTensor, z: types.FloatTensor, r: types.FloatTensor,
            q: types.FloatTensor,
            sigma: types.FloatTensor) -> types.FloatTensor:
  return tf.math.divide_no_nan(
      tf.math.log(z) + (r - q + 0.5 * sigma**2) * tau,
      sigma * tf.math.sqrt(tau))


def _d_minus(tau: types.FloatTensor, z: types.FloatTensor, r: types.FloatTensor,
             q: types.FloatTensor,
             sigma: types.FloatTensor) -> types.FloatTensor:
  return _d_plus(tau, z, r, q, sigma) - sigma * tf.math.sqrt(tau)


def boundary_numerator(
    tau_grid: types.FloatTensor,
    b: Callable[[types.FloatTensor], types.FloatTensor],
    k: types.FloatTensor,
    r: types.FloatTensor,
    q: types.FloatTensor,
    sigma: types.FloatTensor,
    integration_num_points: int = 32,
    dtype: Optional[tf.DType] = None) -> types.FloatTensor:
  """Calculates the numerator of the exercise boundary function of an American option.

  Calculates the numerator part of the calculation required to get the exercise
  boundary function of an American option. This corresponds to `N` in formula
  (3.7) in the paper [1].

  #### References
  [1] Leif Andersen, Mark Lake and Dimitri Offengenden. High-performance
  American option pricing. 2015
  https://engineering.nyu.edu/sites/default/files/2019-03/Carr-adjusting-exponential-levy-models.pdf#page=54

  #### Example
  ```python
    tau_grid = tf.constant([[0., 0.5, 1.], [0., 1., 2.]], dtype=tf.float64)
    k = tf.constant([100, 100], dtype=tf.float64)
    r = tf.constant([0.01, 0.02], dtype=tf.float64)
    q = tf.constant([0.01, 0.02], dtype=tf.float64)
    sigma = tf.constant([0.1, 0.15], dtype=tf.float64)
    k_exp = k[:, tf.newaxis, tf.newaxis]
    r_exp = r[:, tf.newaxis, tf.newaxis]
    q_exp = q[:, tf.newaxis, tf.newaxis]
    def b_0(tau_grid_exp):
      return tf.ones_like(tau_grid_exp) * k_exp * tf.math.minimum(
          tf.constant(1.0, dtype=tf.float64), r_exp/q_exp)
    integration_num_points = 32
    boundary_numerator(tau_grid, b_0, k, r, q, sigma, integration_num_points)
    # tf.constant([[0.5, 0.48835735, 0.4849528],
    #             [0.5, 0.4798061, 0.47702501]], dtype=tf.float64)
  ```

  Args:
    tau_grid: Grid of values of shape `[num_options, grid_num_points]`
      indicating the time left until option maturity.
    b: Represents the exercise boundary function for the option. Receives
      `Tensor` of rank `tau_grid.rank + 1` and returns a `Tensor` of same shape.
    k: Same dtype as `tau_grid` with shape `num_options` representing the strike
      price of the option.
    r: Same shape and dtype as `k` representing the annualized risk-free
      interest rate, continuously compounded.
    q: Same shape and dtype as `k` representing the dividend rate.
    sigma: Same shape and dtype as `k` representing the volatility of the
      option's returns.
    integration_num_points: The number of points used in the integration
      approximation method.
      Default value: 32.
    dtype: If supplied, the dtype for all input tensors. Result will have the
      same dtype.
      Default value: None which maps to dtype of `tau_grid`.

  Returns:
    `Tensor` of shape `[num_options, grid_num_points]`, containing a partial
    result for calculating the exercise boundary.
  """
  with tf.name_scope('calculate_N'):
    # Shape [num_options, grid_num_points]
    tau_grid = tf.convert_to_tensor(tau_grid, dtype=dtype)
    dtype = tau_grid.dtype
    # Shape [num_options]
    k = tf.convert_to_tensor(k, dtype=dtype)
    r = tf.convert_to_tensor(r, dtype=dtype)
    q = tf.convert_to_tensor(q, dtype=dtype)
    sigma = tf.convert_to_tensor(sigma, dtype=dtype)
    # Shape [num_options, 1, 1]
    k_exp = k[:, tf.newaxis, tf.newaxis]
    r_simple_exp = r[:, tf.newaxis]
    r_exp = r_simple_exp[:, tf.newaxis]
    q_exp = q[:, tf.newaxis, tf.newaxis]
    sigma_exp = sigma[:, tf.newaxis, tf.newaxis]
    # Shape [num_options, grid_num_points, 1]
    tau_grid_exp = tf.expand_dims(tau_grid, axis=-1)
    term1 = _standard_normal_cdf(
        _d_minus(tau_grid_exp,
                 b(tau_grid_exp) / k_exp, r_exp, q_exp, sigma_exp))
    # Shape [num_options, grid_num_points]
    term1 = tf.squeeze(term1, axis=-1)
    def func(u):
      # Shape [num_options, grid_num_points, integration_num_points]
      ratio = b(tau_grid_exp) / b(u)
      norm = _standard_normal_cdf(
          _d_minus(tau_grid_exp - u, ratio, r_exp, q_exp, sigma_exp))
      return tf.math.exp(r_exp * u) * norm

    # Shape [num_options, grid_num_points]
    term2 = r_simple_exp * gauss_legendre(
        func=func,
        lower=tf.zeros_like(tau_grid),
        upper=tau_grid,
        num_points=integration_num_points,
        dtype=dtype)
    return term1 + term2


def boundary_denominator(
    tau_grid: types.FloatTensor,
    b: Callable[[types.FloatTensor], types.FloatTensor],
    k: types.FloatTensor,
    r: types.FloatTensor,
    q: types.FloatTensor,
    sigma: types.FloatTensor,
    integration_num_points: int = 32,
    dtype: Optional[tf.DType] = None) -> types.FloatTensor:
  """Calculates the denominator of the exercise boundary function of an American option.

  Calculates the denominator part of the calculation required to get the
  exercise boundary function of an American option. This corresponds to `D` in
  formula (3.8) in the paper [1].

  #### References
  [1] Leif Andersen, Mark Lake and Dimitri Offengenden. High-performance
  American option pricing. 2015
  https://engineering.nyu.edu/sites/default/files/2019-03/Carr-adjusting-exponential-levy-models.pdf#page=54

  #### Example
  ```python
    tau_grid = tf.constant([[0., 0.5, 1.], [0., 1., 2.]], dtype=tf.float64)
    k = tf.constant([100, 100], dtype=tf.float64)
    r = tf.constant([0.01, 0.02], dtype=tf.float64)
    q = tf.constant([0.01, 0.02], dtype=tf.float64)
    sigma = tf.constant([0.1, 0.15], dtype=tf.float64)
    k_exp = k[:, tf.newaxis, tf.newaxis]
    r_exp = r[:, tf.newaxis, tf.newaxis]
    q_exp = q[:, tf.newaxis, tf.newaxis]
    def b_0(tau_grid_exp):
      return tf.ones_like(tau_grid_exp) * k_exp * tf.math.minimum(
          tf.constant(1.0, dtype=tf.float64), r_exp/q_exp)
    integration_num_points = 32
    boundary_denominator(tau_grid, b_0, k, r, q, sigma, integration_num_points)
    # tf.constant([[0.5, 0.51665517, 0.52509737],
    #             [0.5, 0.54039524, 0.56378576]], dtype=tf.float64)
  ```

  Args:
    tau_grid: Grid of values of shape `[num_options, grid_num_points]`
      indicating the time left until option maturity.
    b: Represents the exercise boundary function for the option. Receives
      `Tensor` of rank `tau_grid.rank + 1` and returns a `Tensor` of same shape.
    k: Same dtype as `tau_grid` with shape `num_options` representing the strike
      price of the option.
    r: Same shape and dtype as `k` representing the annualized risk-free
      interest rate, continuously compounded.
    q: Same shape and dtype as `k` representing the dividend rate.
    sigma: Same shape and dtype as `k` representing the volatility of the
      option's returns.
    integration_num_points: The number of points used in the integration
      approximation method.
      Default value: 32.
    dtype: If supplied, the dtype for all input tensors. Result will have the
      same dtype.
      Default value: None which maps to dtype of `tau_grid`.

  Returns:
    `Tensor` of shape `[num_options, grid_num_points]`, containing a partial
    result for calculating the exercise boundary.
  """
  with tf.name_scope('calculate_D'):
    # Shape [num_options, grid_num_points]
    tau_grid = tf.convert_to_tensor(tau_grid, dtype=dtype)
    dtype = tau_grid.dtype
    # Shape [num_options]
    k = tf.convert_to_tensor(k, dtype=dtype)
    r = tf.convert_to_tensor(r, dtype=dtype)
    q = tf.convert_to_tensor(q, dtype=dtype)
    sigma = tf.convert_to_tensor(sigma, dtype=dtype)
    # Shape [num_options, 1, 1]
    k_exp = k[:, tf.newaxis, tf.newaxis]
    r_exp = r[:, tf.newaxis, tf.newaxis]
    q_simple_exp = q[:, tf.newaxis]
    q_exp = q_simple_exp[:, tf.newaxis]
    sigma_exp = sigma[:, tf.newaxis, tf.newaxis]
    # Shape [num_options, grid_num_points, 1]
    tau_grid_exp = tf.expand_dims(tau_grid, axis=-1)
    term1 = _standard_normal_cdf(
        _d_plus(tau_grid_exp, b(tau_grid_exp) / k_exp, r_exp, q_exp, sigma_exp))
    # Shape [num_options, grid_num_points]
    term1 = tf.squeeze(term1, axis=-1)
    def func(u):
      # Shape [num_options, grid_num_points, integration_num_points]
      ratio = b(tau_grid_exp) / b(u)
      norm = _standard_normal_cdf(
          _d_plus(tau_grid_exp - u, ratio, r_exp, q_exp, sigma_exp))
      return tf.math.exp(q_exp * u) * norm

    # Shape [num_options, grid_num_points]
    term2 = q_simple_exp * gauss_legendre(
        func=func,
        lower=tf.zeros_like(tau_grid),
        upper=tau_grid,
        num_points=integration_num_points,
        dtype=dtype)
    return term1 + term2


def exercise_boundary(
    tau_grid: types.FloatTensor,
    k: types.FloatTensor,
    r: types.FloatTensor,
    q: types.FloatTensor,
    sigma: types.FloatTensor,
    max_depth: int = 20,
    tolerance: float = 1e-8,
    integration_num_points: int = 32,
    dtype: Optional[tf.DType] = None
) -> Callable[[types.FloatTensor], types.FloatTensor]:
  """Calculates the exercise boundary function of an American option.

  Iteratively calculates the exercise boundary function of an American option.
  This corresponds to `B` in formula (3.9) in the paper [1].

  #### References
  [1] Leif Andersen, Mark Lake and Dimitri Offengenden. High-performance
  American option pricing. 2015
  https://engineering.nyu.edu/sites/default/files/2019-03/Carr-adjusting-exponential-levy-models.pdf#page=55

  #### Example
  ```python
    tau = tf.constant([1, 2], dtype=tf.float64)
    k = tf.constant([100, 100], dtype=tf.float64)
    r = tf.constant([0.01, 0.02], dtype=tf.float64)
    q = tf.constant([0.01, 0.02], dtype=tf.float64)
    sigma = tf.constant([0.1, 0.15], dtype=tf.float64)
    grid_num_points = 3
    max_depth = 30
    tolerance = 1e-8
    integration_num_points = 32
    tau_grid = tf.linspace(tf.constant(0., dtype=tf.float64), tau,
                          grid_num_points, axis=-1)
    exercise_boundary(tau_grid, k, r, q, sigma, max_depth, tolerance,
                      integration_num_points)
    # tf.constant([[100., 82.51395531, 80.49806099],
    #             [100., 71.00509961, 69.96481827]], dtype=tf.float64)
  ```

  Args:
    tau_grid: Grid of values of shape `[num_options, grid_num_points]`
      indicating the time left until option maturity.
    k: Same dtype as `tau_grid` with shape `num_options` representing the strike
      price of the option.
    r: Same shape and dtype as `k` representing the annualized risk-free
      interest rate, continuously compounded.
    q: Same shape and dtype as `k` representing the dividend rate.
    sigma: Same shape and dtype as `k` representing the volatility of the
      option's returns.
    max_depth: Maximum number of iterations for calculating the exercise
      boundary if it doesn't converge earlier. Default value: 20.
    tolerance: Represents the tolerance for the relative difference between the
      old and new exercise boundary function values, at which to stop further
      calculating a new exercise boundary function.
    integration_num_points: The number of points used in the integration
      approximation method.
      Default value: 32.
    dtype: If supplied, the dtype for all input tensors. Result will have the
      same dtype.
      Default value: None which maps to dtype of `tau`.

  Returns:
    `Callable` expecting `Tensor` of shape `[num_options, grid_num_points, n]`
    as input (where `n` is arbitrary)  and returning `Tensor` of the same shape.
    Represents the exercise boundary function of an American option pricing
    algorithm.
  """
  with tf.name_scope('exercise_boundary'):
    # Shape [num_options, grid_num_points]
    tau_grid = tf.convert_to_tensor(tau_grid, dtype=dtype)
    dtype = tau_grid.dtype
    epsilon = 1e-6
    if dtype == tf.float64:
      epsilon = 1e-10
    # Shape [num_options]
    k = tf.convert_to_tensor(k, dtype=dtype)
    r = tf.convert_to_tensor(r, dtype=dtype)
    q = tf.convert_to_tensor(q, dtype=dtype)
    sigma = tf.convert_to_tensor(sigma, dtype=dtype)
    # Shape [num_options, 1]
    k_exp = tf.expand_dims(k, axis=-1)
    r_exp = tf.expand_dims(r, axis=-1)
    q_exp = tf.expand_dims(q, axis=-1)
    # Shape [num_options, grid_num_points, 1]
    tau_grid_exp = tf.expand_dims(tau_grid, axis=-1)
    def b_0(tau_grid_exp):
      # Shape [num_options, grid_num_points, 1]
      k_exp_exp = tf.expand_dims(k_exp, axis=-1)
      r_exp_exp = tf.expand_dims(r_exp, axis=-1)
      q_exp_exp = tf.expand_dims(q_exp, axis=-1)
      return tf.ones_like(tau_grid_exp) * k_exp_exp * tf.math.minimum(
          tf.constant(1.0, dtype=dtype), r_exp_exp / q_exp_exp)
    def cond(converged, _):
      return tf.math.logical_not(converged)
    def body(converged, current_boundary_points):
      # Shape [num_options, grid_num_points]
      spline_params = build_spline(tau_grid, current_boundary_points)
      def current_exercise_boundary_fn(tau_grid_exp):
        # Reshaping because interpolation needs last dimension to be > 1
        shape_1 = utils.get_shape(tau_grid_exp)[1]
        shape_2 = utils.get_shape(tau_grid_exp)[2]
        tau_grid_exp_reshape = tf.reshape(tau_grid_exp, [-1, shape_1 * shape_2])
        interpolation = interpolate(tau_grid_exp_reshape, spline_params)
        return tf.reshape(interpolation, [-1, shape_1, shape_2])
      # Shape [num_options, grid_num_points]
      numerator = boundary_numerator(tau_grid, current_exercise_boundary_fn, k,
                                     r, q, sigma, integration_num_points)
      denominator = boundary_denominator(tau_grid, current_exercise_boundary_fn,
                                         k, r, q, sigma, integration_num_points)
      new_boundary_points = tf.math.divide_no_nan(
          k_exp * tf.math.exp(-(r_exp - q_exp) * tau_grid) * numerator,
          denominator)
      diff = new_boundary_points - current_boundary_points
      # Shape 0
      relative_error = tf.math.reduce_max(
          tf.math.abs(diff) / (tf.math.abs(new_boundary_points) + epsilon))
      converged = relative_error <= tolerance
      return converged, new_boundary_points
    # Shape 0
    converged = tf.constant(False)
    # Shapes 0, [num_options, grid_num_points]
    loop_vars = (converged, tf.squeeze(b_0(tau_grid_exp), axis=-1))
    # Shapes 0, [num_options, grid_num_points]
    _, result = tf.while_loop(
        cond=cond, body=body, loop_vars=loop_vars, maximum_iterations=max_depth)
    # Shape [num_options, grid_num_points]
    new_spline_params = build_spline(tau_grid, result)
    def new_exercise_boundary_fn(tau_grid_exp):
      # Reshaping because interpolation needs last dimension to be > 1
      shape_1 = utils.get_shape(tau_grid_exp)[1]
      shape_2 = utils.get_shape(tau_grid_exp)[2]
      tau_grid_exp_reshape = tf.reshape(tau_grid_exp, [-1, shape_1 * shape_2])
      interpolation = interpolate(tau_grid_exp_reshape, new_spline_params)
      return tf.reshape(interpolation, [-1, shape_1, shape_2])
    return new_exercise_boundary_fn
