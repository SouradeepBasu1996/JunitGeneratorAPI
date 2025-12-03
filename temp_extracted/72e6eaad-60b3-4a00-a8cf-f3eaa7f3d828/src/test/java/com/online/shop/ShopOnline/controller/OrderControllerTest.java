package com.online.shop.ShopOnline.controller;

import com.google.common.collect.Lists;
import com.online.shop.ShopOnline.controller.OrderController;
import com.online.shop.ShopOnline.controller.OrderRepository;
import com.online.shop.ShopOnline.controller.OrderService;
import java.util.*;
import java.util.ArrayList;
import java.util.Optional;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Mockito;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
public class OrderControllerTest {

    @Mock
    private OrderRepository orderRepository;

    @InjectMocks
    private OrderController orderController;

    @BeforeEach
    void setUp() {
        Mockito.reset(orderRepository);
    }

    @Test
    @DisplayName("shouldReturnOrderWhenIdIsValid")
    void shouldReturnOrderWhenIdIsValid() {
        // Given
        Long id = 1L;
        when(orderRepository.findById(id)).thenReturn(Optional.of(new Order()));

        // When
        ResponseEntity<Order> response = orderController.getOrder(id);

        // Then
        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(new Order(), response.getBody());
    }

    @Test
    @DisplayName("shouldThrowExceptionWhenIdIsInvalid")
    void shouldThrowExceptionWhenIdIsInvalid() {
        // Given
        Long id = 1L;
        when(orderRepository.findById(id)).thenReturn(Optional.empty());

        // When
        ResponseEntity<Order> response = orderController.getOrder(id);

        // Then
        assertEquals(HttpStatus.NOT_FOUND, response.getStatusCode());
    }

    @Test
    @DisplayName("shouldReturnAllOrdersWhenNoFilter")
    void shouldReturnAllOrdersWhenNoFilter() {
        // Given
        when(orderRepository.findAll()).thenReturn(Lists.newArrayList(new Order(), new Order()));

        // When
        ResponseEntity<List<Order>> response = orderController.getOrders();

        // Then
        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(2, response.getBody().size());
    }

    @Test
    @DisplayName("shouldThrowExceptionWhenFilterIsInvalid")
    void shouldThrowExceptionWhenFilterIsInvalid() {
        // Given

        // When
        assertThrows(Exception.class, () -> orderController.getOrders());

        // Then
    }
}