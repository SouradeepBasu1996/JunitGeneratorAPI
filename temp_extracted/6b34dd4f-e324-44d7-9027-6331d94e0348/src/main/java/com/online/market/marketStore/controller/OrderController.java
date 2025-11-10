package com.online.market.marketStore.controller;
import com.online.market.marketStore.entity.Order;
import com.online.market.marketStore.service.OrderService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.beans.factory.annotation.Autowired;

import java.util.List;
import java.util.Optional;

@RestController
@RequestMapping("/order")
public class OrderController{

    @Autowired
    	private OrderService orderService;


	@GetMapping("allOrder/{id}")
	public ResponseEntity<Optional<Order>> getOrderById(@PathVariable(value = "id") Long orderId){
	Optional<Order> order = orderService.findOrderById(orderId);
	return ResponseEntity.ok(order);
	}
	@GetMapping("/all")
	public ResponseEntity<List<Order>> getAllOrders(){
	List<Order> orderList = orderService.findAllOrders();
	return ResponseEntity.ok(orderList);
	}
	@PostMapping("/add")
	public String addOrder(@RequestBody Order order){
	Order orderResponse = orderService.saveOrder(order);
	return "Created"+orderResponse;
	}
	@PutMapping("/update/{id}")
	public ResponseEntity<String> updateOrder(@PathVariable(value = "id") Long orderId){
	return ResponseEntity.ok("Updated Successfully");
	}
	@DeleteMapping("/delete/{id}")
	public ResponseEntity<String> deleteOrder(@PathVariable(value = "id") Long orderId){
	return ResponseEntity.ok("Deleted Successfully");
	}


}