package com.online.market.marketStore.service;

import com.online.market.marketStore.repository.OrderRepository;

import com.online.market.marketStore.entity.Order;

import lombok.AllArgsConstructor;
import org.springframework.stereotype.Service;
import java.util.List;
import java.util.Optional;


@Service
@AllArgsConstructor
public class OrderService{

	private OrderRepository orderRepository;


   // Create
   public Order saveOrder(Order order) {
       return orderRepository.save(order);
   }

   // Read All
   public List<Order> findAllOrders() {
       return orderRepository.findAll();
   }

   // Read by ID
   public Optional<Order> findOrderById(Long id) {
       return orderRepository.findById(id);
   }

   // Update
   public Order updateOrder(Order order) {
       if (orderRepository.existsById(order.getId())) {
           return orderRepository.save(order);
       }
       throw new IllegalArgumentException("Entity not found");
   }

   // Delete
   public void deleteOrderById(Long id) {
       orderRepository.deleteById(id);
   }




}